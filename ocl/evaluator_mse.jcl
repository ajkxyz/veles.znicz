#include "defines.cl"
#include "highlight.cl"


{% set blocks_number = ((max_batch_size + 0.0) / block_size) | round(0, "ceil") | int %}


/// @brief Evaluate MSE.
/// @param y output of the last layer.
/// @param target target values.
/// @param batch_size size of the current batch.
/// @param multiplier coefficient to multiply backpropagated error on.
/// @param metrics [0] - sum of sample's mse, [1] - max of sample's mse, [2] - min of sample's mse.
/// @param err_y output error for backpropagation.
/// @param mse sample's mse.
/// @details We will launch a single workgroup here.

__kernel __attribute__((reqd_work_group_size({{ block_size }}, 1, 1)))
void evaluate_mse(__global const dtype /* IN */ *y,
                  __global const dtype /* IN */ *target,
                  const int /* IN */ batch_size,
                  const dtype /* IN */ multiplier,
                  __global dtype /* IN, OUT */ *metrics,
                  __global dtype /* OUT */ *mse,
                  __global dtype /* OUT */ *err_y) {
  __local dtype SM[{{ block_size }}], SM1[{{ block_size }}], SM2[{{ block_size }}];
  int tx = get_local_id(0);
  int i_sample = tx;
  int y_start = i_sample * {{ output_size }};
  dtype mse_sum = 0, mse_max = 0, mse_min = MAXFLOAT;

  // Compute err_y and fill the confusion matrix
  for (int i = 0; i < {{ blocks_number }}; i++,
       i_sample += {{ block_size }},
       y_start += {{ output_size }} * {{ block_size }}) {
    if (i_sample < batch_size) {
      dtype vle, vle_target, vle_denorm, vle_target_denorm;
      dtype sample_sse = 0;
      for (int j = 0; j < {{ output_size }}; j++) {
        vle = y[y_start + j];
        vle_denorm = denormalize(vle, j);
        vle_target = target[y_start + j];
        vle_target_denorm = denormalize(vle_target, j);
        vle_denorm -= vle_target_denorm;
        sample_sse += vle_denorm * vle_denorm;
        vle -= vle_target;
        vle *= multiplier;
        err_y[y_start + j] = vle;
      }
      {% if root %}
        dtype sample_mse = sqrt(sample_sse / {{ output_size }});
      {% else %}
        dtype sample_mse = sample_sse / {{ output_size }};
      {% endif %}
      mse[i_sample] = sample_mse;
      mse_sum += sample_mse;
      mse_max = max(mse_max, sample_mse);
      mse_min = min(mse_min, sample_mse);
    } else if (i_sample < {{ max_batch_size }}) {
      for (int j = 0; j < {{ output_size }}; j++) {
        err_y[y_start + j] = 0;
      }
      mse[i_sample] = 0;
    }
  }
  // Compute metrics
  SM[tx] = mse_sum;
  SM1[tx] = mse_max;
  SM2[tx] = mse_min;
  barrier(CLK_LOCAL_MEM_FENCE);
  if (!tx) {
    mse_sum = SM[tx];
    mse_max = SM1[tx];
    mse_min = SM2[tx];
    for (int j = 1; j < {{ block_size }}; j++) {
      mse_sum += SM[j];
      mse_max = max(mse_max, SM1[j]);
      mse_min = min(mse_min, SM2[j]);
    }
    metrics[0] += mse_sum;
    metrics[1] = max(metrics[1], mse_max);
    metrics[2] = min(metrics[2], mse_min);
  }
}
