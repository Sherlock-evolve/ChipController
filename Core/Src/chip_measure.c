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

#define CHIP_MEASURE_ADC_TIMEOUT_MS       1000u
#define CHIP_MEASURE_ADC_VREF             5.0f
#define CHIP_MEASURE_PRECISION_FILTER_WORD AD7190_FILTER_WORD_DEFAULT
#define CHIP_MEASURE_HIGH_RATE_FILTER_WORD AD7190_FILTER_WORD_MIN
#define CHIP_MEASURE_CURRENT_SHUNT_OHM    1.0f
#define CHIP_MEASURE_MIN_CURRENT_A        0.000001f
#define CHIP_MEASURE_RELAY_SETTLE_MS      5u
/* External path zero, measured with I+/I- open and V+/V- shorted. */
#define CHIP_MEASURE_CURRENT_ZERO_A       -0.000000535f
#define CHIP_MEASURE_VOLTAGE_ZERO_V       0.00000603f
/* External path gain, measured against a 150.002 ohm load and DMM voltage. */
#define CHIP_MEASURE_CURRENT_GAIN         1.00091f
#define CHIP_MEASURE_VOLTAGE_GAIN         1.00329f

extern SPI_HandleTypeDef hspi1;
extern SPI_HandleTypeDef hspi2;

static AD7190_Handle s_current_adc = {
  .hspi = &hspi1,
  .sync_port = SPI1_SYNC_GPIO_Port,
  .sync_pin = SPI1_SYNC_Pin,
  .vref_volts = CHIP_MEASURE_ADC_VREF,
  .gain = AD7190_GAIN_16,
  .filter_word = CHIP_MEASURE_PRECISION_FILTER_WORD,
  .timeout_ms = CHIP_MEASURE_ADC_TIMEOUT_MS
};

static AD7190_Handle s_voltage_adc = {
  .hspi = &hspi2,
  .sync_port = SPI2_SYNC_GPIO_Port,
  .sync_pin = SPI2_SYNC_Pin,
  .vref_volts = CHIP_MEASURE_ADC_VREF,
  .gain = AD7190_GAIN_1,
  .filter_word = CHIP_MEASURE_PRECISION_FILTER_WORD,
  .timeout_ms = CHIP_MEASURE_ADC_TIMEOUT_MS
};

static ChipMeasure_SampleMode s_sample_mode = CHIP_MEASURE_SAMPLE_MODE_PRECISION;

static ChipMeasure_Status chip_measure_from_ad7190_status(AD7190_Status status);
static ChipMeasure_Status chip_measure_apply_sample_mode(ChipMeasure_SampleMode mode);
static ChipMeasure_Status chip_measure_configure_current_adc(uint16_t filter_word);
static ChipMeasure_Status chip_measure_configure_voltage_adc(uint16_t filter_word);
static uint16_t chip_measure_adc_filter_word_for_mode(ChipMeasure_SampleMode mode);
static ChipMeasure_Status chip_measure_read_synchronized(ChipMeasure_Path path,
                                                         ChipMeasure_SyncSample *sample,
                                                         uint8_t select_path,
                                                         uint8_t start_single,
                                                         uint8_t wait_both_ready);
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

  status = AD7190_Init(&s_voltage_adc);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  s_sample_mode = CHIP_MEASURE_SAMPLE_MODE_PRECISION;
  return chip_measure_apply_sample_mode(s_sample_mode);
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

ChipMeasure_Status ChipMeasure_SetSampleMode(ChipMeasure_SampleMode mode)
{
  ChipMeasure_Status status;

  if ((mode != CHIP_MEASURE_SAMPLE_MODE_PRECISION) &&
      (mode != CHIP_MEASURE_SAMPLE_MODE_HIGH_RATE))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  if (mode == s_sample_mode)
  {
    return CHIP_MEASURE_OK;
  }

  status = chip_measure_apply_sample_mode(mode);
  if (status == CHIP_MEASURE_OK)
  {
    s_sample_mode = mode;
  }
  else
  {
    (void)chip_measure_apply_sample_mode(s_sample_mode);
  }

  return status;
}

ChipMeasure_SampleMode ChipMeasure_GetSampleMode(void)
{
  return s_sample_mode;
}

uint16_t ChipMeasure_GetAdcFilterWord(void)
{
  return chip_measure_adc_filter_word_for_mode(s_sample_mode);
}

const char *ChipMeasure_SampleModeText(ChipMeasure_SampleMode mode)
{
  switch (mode)
  {
    case CHIP_MEASURE_SAMPLE_MODE_PRECISION:
      return "PRECISION";
    case CHIP_MEASURE_SAMPLE_MODE_HIGH_RATE:
      return "HIGH_RATE";
    default:
      return "UNKNOWN";
  }
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
  return chip_measure_read_synchronized(path, sample, 1u, 1u, 1u);
}

ChipMeasure_Status ChipMeasure_ReadSynchronizedFast(ChipMeasure_Path path, ChipMeasure_SyncSample *sample)
{
  return chip_measure_read_synchronized(path, sample, 0u, 1u, 0u);
}

ChipMeasure_Status ChipMeasure_StartHighRateStream(ChipMeasure_Path path)
{
  ChipMeasure_Status measure_status;
  AD7190_Status adc_status;

  if ((path != CHIP_MEASURE_PATH_EXTERNAL) && (path != CHIP_MEASURE_PATH_INTERNAL_R42))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  measure_status = ChipMeasure_SelectPath(path);
  if (measure_status != CHIP_MEASURE_OK)
  {
    return measure_status;
  }

  chip_measure_set_adc_sync(0u);

  adc_status = AD7190_StartContinuous(&s_current_adc);
  if (adc_status != AD7190_OK)
  {
    chip_measure_set_adc_sync(1u);
    return chip_measure_from_ad7190_status(adc_status);
  }

  adc_status = AD7190_StartContinuous(&s_voltage_adc);
  if (adc_status != AD7190_OK)
  {
    chip_measure_set_adc_sync(1u);
    return chip_measure_from_ad7190_status(adc_status);
  }

  chip_measure_set_adc_sync(1u);

  return CHIP_MEASURE_OK;
}

ChipMeasure_Status ChipMeasure_ReadHighRateStreamSample(ChipMeasure_Path path, ChipMeasure_SyncSample *sample)
{
  return chip_measure_read_synchronized(path, sample, 0u, 0u, 0u);
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

static ChipMeasure_Status chip_measure_read_synchronized(ChipMeasure_Path path,
                                                         ChipMeasure_SyncSample *sample,
                                                         uint8_t select_path,
                                                         uint8_t start_single,
                                                         uint8_t wait_both_ready)
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

  if ((path != CHIP_MEASURE_PATH_EXTERNAL) && (path != CHIP_MEASURE_PATH_INTERNAL_R42))
  {
    return CHIP_MEASURE_INVALID_PARAM;
  }

  if (select_path != 0u)
  {
    measure_status = ChipMeasure_SelectPath(path);
    if (measure_status != CHIP_MEASURE_OK)
    {
      return measure_status;
    }
  }

  if (start_single != 0u)
  {
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
  }

  adc_status = AD7190_WaitReady(&s_current_adc, &current_status);
  if (adc_status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(adc_status);
  }

  if (wait_both_ready != 0u)
  {
    adc_status = AD7190_WaitReady(&s_voltage_adc, &voltage_status);
    if (adc_status != AD7190_OK)
    {
      return chip_measure_from_ad7190_status(adc_status);
    }
  }
  else
  {
    /*
     * High-rate paths start both ADCs from a shared SYNC release. Waiting on
     * one RDY avoids a second status poll after the paired conversion is ready.
     */
    voltage_status = 0u;
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
    case AD7190_ERROR:
    default:
      return CHIP_MEASURE_ERROR;
  }
}

static ChipMeasure_Status chip_measure_apply_sample_mode(ChipMeasure_SampleMode mode)
{
  ChipMeasure_Status status;
  uint16_t filter_word;

  filter_word = chip_measure_adc_filter_word_for_mode(mode);

  status = ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
  if (status != CHIP_MEASURE_OK)
  {
    return status;
  }

  chip_measure_set_adc_sync(1u);

  status = chip_measure_configure_current_adc(filter_word);
  if (status != CHIP_MEASURE_OK)
  {
    return status;
  }

  status = chip_measure_configure_voltage_adc(filter_word);
  if (status != CHIP_MEASURE_OK)
  {
    return status;
  }

  return CHIP_MEASURE_OK;
}

static ChipMeasure_Status chip_measure_configure_current_adc(uint16_t filter_word)
{
  AD7190_Status status;

  status = AD7190_SetFilterWord(&s_current_adc, filter_word);
  if (status != AD7190_OK)
  {
    return chip_measure_from_ad7190_status(status);
  }

  status = AD7190_Configure(&s_current_adc,
                            AD7190_CHANNEL_AIN1_AIN2,
                            AD7190_GAIN_16,
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

  return CHIP_MEASURE_OK;
}

static ChipMeasure_Status chip_measure_configure_voltage_adc(uint16_t filter_word)
{
  AD7190_Status status;

  status = AD7190_SetFilterWord(&s_voltage_adc, filter_word);
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

static uint16_t chip_measure_adc_filter_word_for_mode(ChipMeasure_SampleMode mode)
{
  if (mode == CHIP_MEASURE_SAMPLE_MODE_HIGH_RATE)
  {
    return CHIP_MEASURE_HIGH_RATE_FILTER_WORD;
  }

  return CHIP_MEASURE_PRECISION_FILTER_WORD;
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
