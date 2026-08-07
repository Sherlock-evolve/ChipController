/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    chip_measure.c
  * @brief   Board-level measurement helpers for the chip controller board.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "chip_measure.h"
#include "main.h"

#define CHIP_MEASURE_ADC_TIMEOUT_MS       1500u
#define CHIP_MEASURE_ADC_VREF             5.0f
#define CHIP_MEASURE_CURRENT_SHUNT_OHM    1.0f
#define CHIP_MEASURE_MIN_CURRENT_A        0.000001f
#define CHIP_MEASURE_RELAY_SETTLE_MS      5u
/* G128/FS480 external-path calibration.  The current "zero" is the effective
 * loaded operating-point offset fitted over 0.3-12 mA with a 150.002 ohm
 * reference; it intentionally differs from the -0.585095 uA open-circuit
 * physical zero.  The voltage zero is the open/short physical-path value. */
#define CHIP_MEASURE_CURRENT_ZERO_A       -0.000000800737f
#define CHIP_MEASURE_VOLTAGE_ZERO_V       0.000004739f
/* Current gain includes the 2026-08-07 residual trim from the first increasing
 * 0.3-12 mA sweep with a 150.002 ohm reference.  Voltage gain remains the
 * independently established external-path voltage correction. */
#define CHIP_MEASURE_CURRENT_GAIN         1.000719600f
#define CHIP_MEASURE_VOLTAGE_GAIN         1.00329f
/* Effective voltage-sense loading compensation for U14 unbuffered conversions.
 * Keep the historical 150.007 ohm model anchor independently of the latest
 * 150.002 ohm zero/gain fit, and apply only the incremental correction above
 * it. Reported I/V stay raw. */
#define CHIP_MEASURE_VOLTAGE_SENSE_LOAD_OHM   330000.0f
#define CHIP_MEASURE_RESISTANCE_ANCHOR_OHM    150.007f

extern SPI_HandleTypeDef hspi1;
extern SPI_HandleTypeDef hspi2;

static AD7190_Handle s_current_adc = {
  .hspi = &hspi1,
  .sync_port = SPI1_SYNC_GPIO_Port,
  .sync_pin = SPI1_SYNC_Pin,
  .vref_volts = CHIP_MEASURE_ADC_VREF,
  .gain = AD7190_GAIN_128,
  .timeout_ms = CHIP_MEASURE_ADC_TIMEOUT_MS
};

static AD7190_Handle s_voltage_adc = {
  .hspi = &hspi2,
  .sync_port = SPI2_SYNC_GPIO_Port,
  .sync_pin = SPI2_SYNC_Pin,
  .vref_volts = CHIP_MEASURE_ADC_VREF,
  .gain = AD7190_GAIN_1,
  .timeout_ms = CHIP_MEASURE_ADC_TIMEOUT_MS
};

static ChipMeasure_Status chip_measure_from_ad7190_status(AD7190_Status status);
static void chip_measure_set_adc_sync(uint8_t released);
static float chip_measure_calibrate_current_sense(ChipMeasure_Path path, float raw_sense_voltage_v);
static float chip_measure_calibrate_load_voltage(ChipMeasure_Path path, float raw_voltage_v);
static float chip_measure_absf(float value);

ChipMeasure_Status ChipMeasure_Init(void)
{
  AD7190_Status status;

  ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);

  status = AD7190_Init(&s_current_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_Configure(&s_current_adc,
                            AD7190_CHANNEL_AIN1_AIN2,
                            AD7190_GAIN_128,
                            1u,
                            0u,
                            0u);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_CalibrateZeroScale(&s_current_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_CalibrateFullScale(&s_current_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_Init(&s_voltage_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_Configure(&s_voltage_adc,
                            AD7190_CHANNEL_AIN1_AIN2,
                            AD7190_GAIN_1,
                            1u,
                            0u,
                            0u);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_CalibrateZeroScale(&s_voltage_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_CalibrateFullScale(&s_voltage_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_ReadAdcIds(uint8_t *current_adc_id, uint8_t *voltage_adc_id)
{
  AD7190_Status status;

  if ((current_adc_id == NULL) || (voltage_adc_id == NULL))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  status = AD7190_ReadId(&s_current_adc, current_adc_id);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_ReadId(&s_voltage_adc, voltage_adc_id);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_SelectPath(ChipMeasure_Path path)
{
  switch (path)
  {
    case CHIP_MEASURE_PATH_EXTERNAL:
      HAL_GPIO_WritePin(CHIP1_GPIO_Port, CHIP1_Pin, GPIO_PIN_SET);
      HAL_GPIO_WritePin(CHIP2_GPIO_Port, CHIP2_Pin, GPIO_PIN_SET);
      break;

    case CHIP_MEASURE_PATH_INTERNAL_R42:
      HAL_GPIO_WritePin(CHIP1_GPIO_Port, CHIP1_Pin, GPIO_PIN_RESET);
      HAL_GPIO_WritePin(CHIP2_GPIO_Port, CHIP2_Pin, GPIO_PIN_RESET);
      break;

    default:
      return CHIP_MEASURE_INVALID_PARAM;
  }

  HAL_Delay(CHIP_MEASURE_RELAY_SETTLE_MS);
  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_ReadCurrent(ChipMeasure_Path path, float *current_a, float *sense_voltage_v)
{
  AD7190_Reading reading;
  AD7190_Status status;

  if ((current_a == NULL) || (sense_voltage_v == NULL))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  if ((path != CHIP_MEASURE_PATH_EXTERNAL) && (path != CHIP_MEASURE_PATH_INTERNAL_R42))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  status = AD7190_ReadSingle(&s_current_adc, &reading);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  *sense_voltage_v = chip_measure_calibrate_current_sense(path, reading.voltage);
  *current_a = *sense_voltage_v / CHIP_MEASURE_CURRENT_SHUNT_OHM;

  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_ReadLoadVoltage(ChipMeasure_Path path,
                                               float *load_voltage_v,
                                               float *raw_voltage_v)
{
  AD7190_Reading reading;
  AD7190_Status status;

  if ((load_voltage_v == NULL) || (raw_voltage_v == NULL))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  if ((path != CHIP_MEASURE_PATH_EXTERNAL) && (path != CHIP_MEASURE_PATH_INTERNAL_R42))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  status = AD7190_ReadSingle(&s_voltage_adc, &reading);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  *raw_voltage_v = reading.voltage;

  if (path == CHIP_MEASURE_PATH_INTERNAL_R42)
  {
    *load_voltage_v = -*raw_voltage_v;
  }
  else if (path == CHIP_MEASURE_PATH_EXTERNAL)
  {
    *load_voltage_v = chip_measure_calibrate_load_voltage(path, *raw_voltage_v);
  }
  else
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_ReadSynchronized(ChipMeasure_Path path, ChipMeasure_SyncSample *sample)
{
  AD7190_Reading current_reading;
  AD7190_Reading voltage_reading;
  AD7190_Status adc_status;
  ChipMeasure_Status measure_status;
  uint8_t current_status = 0u;
  uint8_t voltage_status = 0u;

  if (sample == NULL)
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  sample->current_sense_voltage_v = 0.0f;
  sample->current_a = 0.0f;
  sample->load_voltage_raw_v = 0.0f;
  sample->load_voltage_v = 0.0f;
  sample->current_adc_status = 0u;
  sample->voltage_adc_status = 0u;

  measure_status = ChipMeasure_SelectPath(path);
  if (measure_status != CHIP_MEASURE_OK)
  {
    return measure_status;
  }

  chip_measure_set_adc_sync(0u);

  adc_status = AD7190_StartSingle(&s_current_adc);
  if (adc_status != AD7190_OK)
  {
    chip_measure_set_adc_sync(1u);
    return chip_measure_from_ad7190_status(adc_status);
  }

  adc_status = AD7190_StartSingle(&s_voltage_adc);
  if (adc_status != AD7190_OK)
  {
    chip_measure_set_adc_sync(1u);
    return chip_measure_from_ad7190_status(adc_status);
  }

  chip_measure_set_adc_sync(1u);

  adc_status = AD7190_WaitReady(&s_current_adc, &current_status);
  if (adc_status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(adc_status);
  }

  adc_status = AD7190_WaitReady(&s_voltage_adc, &voltage_status);
  if (adc_status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(adc_status);
  }

  adc_status = AD7190_ReadData(&s_current_adc, current_status, &current_reading);
  if (adc_status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(adc_status);
  }

  adc_status = AD7190_ReadData(&s_voltage_adc, voltage_status, &voltage_reading);
  if (adc_status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(adc_status);
  }

  sample->current_sense_voltage_v = chip_measure_calibrate_current_sense(path, current_reading.voltage);
  sample->current_a = sample->current_sense_voltage_v / CHIP_MEASURE_CURRENT_SHUNT_OHM;
  sample->load_voltage_raw_v = voltage_reading.voltage;
  sample->current_adc_status = current_reading.status;
  sample->voltage_adc_status = voltage_reading.status;

  if (path == CHIP_MEASURE_PATH_INTERNAL_R42)
  {
    sample->load_voltage_v = -sample->load_voltage_raw_v;
  }
  else if (path == CHIP_MEASURE_PATH_EXTERNAL)
  {
    sample->load_voltage_v = chip_measure_calibrate_load_voltage(path, sample->load_voltage_raw_v);
  }
  else
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  return CHIP_MEASURE_OK;
}

void ChipMeasure_ResetSyncFilter(ChipMeasure_SyncFilter *filter)
{
  if (filter != NULL)
  {
    filter->valid = 0u;
  }
}

ChipMeasure_Status ChipMeasure_FilterSynchronized(ChipMeasure_Path path,
                                                 const ChipMeasure_SyncSample *input,
                                                 ChipMeasure_SyncFilter *filter,
                                                 float alpha,
                                                 ChipMeasure_SyncSample *output)
{
  if ((input == NULL) || (filter == NULL) || (output == NULL) ||
      (alpha <= 0.0f) || (alpha > 1.0f))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  if ((path != CHIP_MEASURE_PATH_EXTERNAL) && (path != CHIP_MEASURE_PATH_INTERNAL_R42))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  if ((filter->valid == 0u) || (filter->path != path))
  {
    filter->sample = *input;
    filter->path = path;
    filter->valid = 1u;
  }
  else
  {
    filter->sample.current_sense_voltage_v +=
        alpha *
        (input->current_sense_voltage_v - filter->sample.current_sense_voltage_v);
    filter->sample.current_a +=
        alpha * (input->current_a - filter->sample.current_a);
    filter->sample.load_voltage_raw_v +=
        alpha *
        (input->load_voltage_raw_v - filter->sample.load_voltage_raw_v);
    filter->sample.load_voltage_v +=
        alpha * (input->load_voltage_v - filter->sample.load_voltage_v);
    filter->sample.current_adc_status = input->current_adc_status;
    filter->sample.voltage_adc_status = input->voltage_adc_status;
  }

  *output = filter->sample;
  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_ReadSynchronizedFiltered(ChipMeasure_Path path,
                                                       ChipMeasure_SyncFilter *filter,
                                                       ChipMeasure_SyncSample *sample)
{
  ChipMeasure_SyncSample raw_sample;
  ChipMeasure_Status status;

  if ((filter == NULL) || (sample == NULL))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  status = ChipMeasure_ReadSynchronized(path, &raw_sample);
  if (status != CHIP_MEASURE_OK)
  {
    return status;
  }

  return ChipMeasure_FilterSynchronized(path,
                                        &raw_sample,
                                        filter,
                                        CHIP_MEASURE_DISPLAY_FILTER_ALPHA,
                                        sample);
}

ChipMeasure_Status ChipMeasure_ReadInternalR42(ChipMeasure_R42Sample *sample)
{
  ChipMeasure_Status status;

  if (sample == NULL)
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  sample->current_sense_voltage_v = 0.0f;
  sample->current_a = 0.0f;
  sample->load_voltage_raw_v = 0.0f;
  sample->load_voltage_v = 0.0f;
  sample->resistance_ohm = 0.0f;
  sample->resistance_valid = 0u;

  status = ChipMeasure_SelectPath(CHIP_MEASURE_PATH_INTERNAL_R42);
  if (status != CHIP_MEASURE_OK)
  {
    return status;
  }

  status = ChipMeasure_ReadCurrent(CHIP_MEASURE_PATH_INTERNAL_R42,
                                   &sample->current_a,
                                   &sample->current_sense_voltage_v);
  if (status != CHIP_MEASURE_OK)
  {
    (void)ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
    return status;
  }

  status = ChipMeasure_ReadLoadVoltage(CHIP_MEASURE_PATH_INTERNAL_R42,
                                       &sample->load_voltage_v,
                                       &sample->load_voltage_raw_v);
  if (status != CHIP_MEASURE_OK)
  {
    (void)ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
    return status;
  }

  if (chip_measure_absf(sample->current_a) < CHIP_MEASURE_MIN_CURRENT_A)
  {
    (void)ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
    return CHIP_MEASURE_NO_CURRENT;
  }

  sample->resistance_ohm = chip_measure_absf(sample->load_voltage_v) / chip_measure_absf(sample->current_a);
  sample->resistance_valid = 1u;

  (void)ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
  return CHIP_MEASURE_OK;
}

uint8_t ChipMeasure_ComputeExternalResistance(float load_voltage_v,
                                              float total_current_a,
                                              float *resistance_ohm)
{
  float voltage_abs_v;
  float total_current_abs_a;
  float sense_branch_current_a;
  float load_current_a;
  float raw_resistance_ohm;
  float anchor_compensated_ohm;
  float anchor_delta_ohm;

  if (resistance_ohm == NULL)
  {
    return 0u;
  }

  *resistance_ohm = 0.0f;
  voltage_abs_v = chip_measure_absf(load_voltage_v);
  total_current_abs_a = chip_measure_absf(total_current_a);

  if (total_current_abs_a < CHIP_MEASURE_MIN_CURRENT_A)
  {
    return 0u;
  }

  raw_resistance_ohm = voltage_abs_v / total_current_abs_a;
  if (raw_resistance_ohm <= CHIP_MEASURE_RESISTANCE_ANCHOR_OHM)
  {
    *resistance_ohm = raw_resistance_ohm;
    return 1u;
  }

  sense_branch_current_a = voltage_abs_v / CHIP_MEASURE_VOLTAGE_SENSE_LOAD_OHM;
  if (sense_branch_current_a >= total_current_abs_a)
  {
    return 0u;
  }

  load_current_a = total_current_abs_a - sense_branch_current_a;
  if (load_current_a < CHIP_MEASURE_MIN_CURRENT_A)
  {
    return 0u;
  }

  anchor_compensated_ohm =
      CHIP_MEASURE_RESISTANCE_ANCHOR_OHM /
      (1.0f - (CHIP_MEASURE_RESISTANCE_ANCHOR_OHM / CHIP_MEASURE_VOLTAGE_SENSE_LOAD_OHM));
  anchor_delta_ohm = anchor_compensated_ohm - CHIP_MEASURE_RESISTANCE_ANCHOR_OHM;
  *resistance_ohm = (voltage_abs_v / load_current_a) - anchor_delta_ohm;
  if (*resistance_ohm < 0.0f)
  {
    *resistance_ohm = 0.0f;
    return 0u;
  }

  return 1u;
}

static ChipMeasure_Status chip_measure_from_ad7190_status(AD7190_Status status)
{
  switch (status)
  {
    case AD7190_OK:
      return CHIP_MEASURE_OK;
    case AD7190_TIMEOUT:
      return CHIP_MEASURE_TIMEOUT;
    case AD7190_BAD_ID:
      return CHIP_MEASURE_BAD_ID;
    case AD7190_INVALID_PARAM:
      return CHIP_MEASURE_INVALID_PARAM;
    case AD7190_SATURATED:
      return CHIP_MEASURE_SATURATED;
    case AD7190_ERROR:
    default:
      return CHIP_MEASURE_ERROR;
  }
}

static void chip_measure_set_adc_sync(uint8_t released)
{
  GPIO_PinState state = (released != 0u) ? GPIO_PIN_SET : GPIO_PIN_RESET;

  if ((s_current_adc.sync_port != NULL) && (s_voltage_adc.sync_port == s_current_adc.sync_port))
  {
    HAL_GPIO_WritePin(s_current_adc.sync_port,
                      s_current_adc.sync_pin | s_voltage_adc.sync_pin,
                      state);
    return;
  }

  if (s_current_adc.sync_port != NULL)
  {
    HAL_GPIO_WritePin(s_current_adc.sync_port, s_current_adc.sync_pin, state);
  }

  if (s_voltage_adc.sync_port != NULL)
  {
    HAL_GPIO_WritePin(s_voltage_adc.sync_port, s_voltage_adc.sync_pin, state);
  }
}

static float chip_measure_calibrate_current_sense(ChipMeasure_Path path, float raw_sense_voltage_v)
{
  if (path == CHIP_MEASURE_PATH_EXTERNAL)
  {
    return (raw_sense_voltage_v - (CHIP_MEASURE_CURRENT_ZERO_A * CHIP_MEASURE_CURRENT_SHUNT_OHM)) *
           CHIP_MEASURE_CURRENT_GAIN;
  }

  return raw_sense_voltage_v;
}

static float chip_measure_calibrate_load_voltage(ChipMeasure_Path path, float raw_voltage_v)
{
  if (path == CHIP_MEASURE_PATH_EXTERNAL)
  {
    return (raw_voltage_v - CHIP_MEASURE_VOLTAGE_ZERO_V) * CHIP_MEASURE_VOLTAGE_GAIN;
  }

  return raw_voltage_v;
}

static float chip_measure_absf(float value)
{
  return (value < 0.0f) ? -value : value;
}
