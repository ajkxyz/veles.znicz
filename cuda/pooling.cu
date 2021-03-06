#include "pooling_common.cu"
#include "random.cu"

/// @brief Does max pooling over convolutional layer output.
/// @param h batch of input multichannel interleaved images.
/// @param y batch of output multichannel interleaved images.
/// @param h_offs indexes of y value in corresponding to it h array.
/// @details If ABS_VALUES is defined, compare absolute values; otherwise,
/// as usual.
/// Should be defined externally:
///          SX - input image width,
///          SY - input image height,
///          N_CHANNELS - number of input channels,
///          KX - pooling kernel width,
///          KY - pooling kernel height,
///          SLIDE_X - kernel sliding by x-axis,
///          SLIDE_Y - kernel sliding by y-axis.
///          Kernel should be run as:
///          global_size = [out_width, out_height],
///          local_size = None.
extern "C"
__global__ void max_pooling(const dtype *h, dtype *y, int *h_offs) {
  int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= OUTPUT_SIZE) {
    return;
  }

  int target_y = idx / (OUT_SX * N_CHANNELS);
  int target_x = idx % (OUT_SX * N_CHANNELS);

  dtype max_vle = -FLT_MAX;
#ifdef ABS_VALUES
  dtype max_absvle = -1;
#endif
  int max_offs = 0;

  int start_x = TARGET_PIXEL_X * SLIDE_X * N_CHANNELS + TARGET_CHANNEL;
  int start_y = target_y % OUT_SY * SLIDE_Y;
  int offs = ((target_y / OUT_SY) * SY + start_y) * SX * N_CHANNELS;

#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY); i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS); j++, x += N_CHANNELS) {
#endif
      dtype vle = h[offs + x];
#ifdef ABS_VALUES
      dtype absvle = fabs(vle);
      bool hit = (absvle > max_absvle);
      max_absvle = (hit) ? absvle : max_absvle;
#else
      bool hit = (vle > max_vle);
#endif
      max_vle = (hit) ? vle : max_vle;
      max_offs = (hit) ? offs + x : max_offs;
    }
  }

  y[idx] = max_vle;
  h_offs[idx] = max_offs;
}


/// @brief Does avg pooling over convolutional layer output.
/// @param h batch of input multichannel interleaved images.
/// @param y batch of output multichannel interleaved images.
extern "C"
__global__ void avg_pooling(const dtype /* IN */  *h, dtype /* OUT */ *y) {
  int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= OUTPUT_SIZE) {
    return;
  }

  int target_y = idx / (OUT_SX * N_CHANNELS);
  int target_x = idx % (OUT_SX * N_CHANNELS);

  dtype smm = 0;

  int start_x = TARGET_PIXEL_X * SLIDE_X * N_CHANNELS + TARGET_CHANNEL;
  int start_y = target_y % OUT_SY * SLIDE_Y;
  int offs = ((target_y / OUT_SY) * SY + start_y) * SX * N_CHANNELS;

#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY); i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS); j++, x += N_CHANNELS) {
#endif
      smm += h[offs + x];
    }
  }

#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  #define NY KY
#else
  #define NY MIN(KY, SY - (target_y % OUT_SY) * SLIDE_Y)
#endif

#if (OUT_SX - 1) * SLIDE_X + KX == SX
  #define NX KX
#else
  #define NX MIN(KX, SX - TARGET_PIXEL_X * SLIDE_X)
#endif

  y[idx] = smm / (NX * NY);

#undef NX
#undef NY
}


/// @brief Does stochastic pooling over convolutional layer output.
/// @param h batch of input multichannel interleaved images.
/// @param y batch of output multichannel interleaved images.
/// @param h_offs indexes of y value in corresponding to it h array.
/// @param rand random numbers.
/// @details If ABS_VALUES is defined, use absolute values; otherwise,
/// discard negative ones.
/// Should be defined externally:
///          SX - input image width,
///          SY - input image height,
///          N_CHANNELS - number of input channels,
///          KX - pooling kernel width,
///          KY - pooling kernel height,
///          SLIDE_X - kernel sliding by x-axis,
///          SLIDE_Y - kernel sliding by y-axis.
///          Kernel should be run as:
///          global_size = [out_width, out_height],
///          local_size = None.
#if KX * KY > 65536
#error "Too large kernel size for the current stochastic pooling implementation"
#endif
extern "C"
__global__ void stochastic_pooling(
    const dtype /* IN */ *h, dtype /* OUT */ *y, int /* OUT */ *h_offs,
    ushort  /* IN, OUT */ *rand) {

  int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= OUTPUT_SIZE) {
    return;
  }

  int target_y = idx / (OUT_SX * N_CHANNELS);
  int target_x = idx % (OUT_SX * N_CHANNELS);

  int start_x = TARGET_PIXEL_X * SLIDE_X * N_CHANNELS + TARGET_CHANNEL;
  int start_y = target_y % OUT_SY * SLIDE_Y;
  int offs = ((target_y / OUT_SY) * SY + start_y) * SX * N_CHANNELS;
  int original_offset = offs;
  dtype sum = 0;
  int count = 0;

#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY);
      i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS, count++) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS);
         j++, x += N_CHANNELS, count++) {
#endif
      dtype val = h[offs + x];
#ifdef ABS_VALUES
      val = fabs(val);
#else
      val = fmax(val, (dtype)0);
#endif
      sum += val;
    }
  }

  ushort random = rand[idx];
  // The index of the passed through
  int lucky = 0;
  // All elements can be <= 0
  dtype pos_add = (sum == 0) ? 1 : 0;
  dtype pos_factor = (sum == 0) ? count : sum;
  dtype pos = (pos_factor * random) / 65536;
  sum = 0;

  // This is not just copy-paste of previous for-s
  offs = original_offset;
#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY);
       i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS);
         j++, x += N_CHANNELS) {
#endif
      dtype val = h[offs + x];
#ifdef ABS_VALUES
      val = fabs(val);
#else
      val = fmax(val, (dtype)0);
#endif
      sum += val;
      sum += pos_add;

      lucky = (pos <= sum) ? offs + x : lucky;
      sum = (pos <= sum) ? -FLT_MAX : sum;
    }
  }

  y[idx] = h[lucky];
  h_offs[idx] = lucky;
}


#ifdef USE_POOLING_DEPOOLING
#if (KX != SLIDE_X) || (KY != SLIDE_Y)
#error "Sliding should be equal to the kernel size for the current implementation"
#endif
extern "C"
__global__
void stochastic_pooling_depooling(dtype *h, const ushort *rand) {
  
  int idx = blockIdx.x * blockDim.x + threadIdx.x;
  if (idx >= OUTPUT_SIZE) {
    return;
  }

  int target_y = idx / (OUT_SX * N_CHANNELS);
  int target_x = idx % (OUT_SX * N_CHANNELS);

  int start_x = TARGET_PIXEL_X * SLIDE_X * N_CHANNELS + TARGET_CHANNEL,
      start_y = target_y % OUT_SY * SLIDE_Y;
  int offs = ((target_y / OUT_SY) * SY + start_y) * SX * N_CHANNELS;
  int original_offset = offs;
  dtype sum = 0;
  int count = 0;

#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY);
       i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS, count++) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS);
         j++, x += N_CHANNELS, count++) {
#endif
      dtype val = h[offs + x];
#ifdef ABS_VALUES
      val = fabs(val);
#else
      val = fmax(val, (dtype)0);
#endif
      sum += val;
    }
  }

  ushort random = rand[idx];
  // The index of the passed through
  int lucky = 0;
  // All elements can be <= 0
  dtype pos_add = (sum == 0) ? 1 : 0;
  dtype pos_factor = (sum == 0) ? count : sum;
  dtype pos = (pos_factor * random) / 65536;
  sum = 0;

  // This is not just copy-paste of previous for-s
  offs = original_offset;
#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY);
       i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS);
         j++, x += N_CHANNELS) {
#endif
      dtype val = h[offs + x];
#ifdef ABS_VALUES
      val = fabs(val);
#else
      val = fmax(val, (dtype)0);
#endif
      sum += val;
      sum += pos_add;

      lucky = (pos <= sum) ? offs + x : lucky;
      sum = (pos <= sum) ? -FLT_MAX : sum;
    }
  }

  dtype chosen_value = h[lucky];

  // This is not just copy-paste of previous for-s
  offs = original_offset;
#if (OUT_SY - 1) * SLIDE_Y + KY == SY
  // No partial windows at the bottom
  for (int i = 0; i < KY; i++, offs += SX * N_CHANNELS) {
#else
  // There are partial windows at the bottom
  for (int i = 0, y = start_y; (i < KY) && (y < SY);
       i++, y++, offs += SX * N_CHANNELS) {
#endif
#if (OUT_SX - 1) * SLIDE_X + KX == SX
    // No partial windows at the right
    for (int j = 0, x = start_x; j < KX; j++, x += N_CHANNELS) {
#else
    // There are partial windows at the right
    for (int j = 0, x = start_x; (j < KX) && (x < SX * N_CHANNELS);
         j++, x += N_CHANNELS) {
#endif
      h[offs + x] = (offs + x == lucky) ? chosen_value : 0;
    }
  }
}
#endif  // USE_POOLING_DEPOOLING


#undef TARGET_CHANNEL
#undef TARGET_PIXEL_X
#undef OUT_SY
#undef OUT_SX
