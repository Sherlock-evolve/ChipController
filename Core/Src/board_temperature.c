/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_temperature.c
  * @brief   Optional board temperature sensor wrapper.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "board_temperature.h"

#define BOARD_TEMPERATURE_I2C_TIMEOUT_MS 100u

extern I2C_HandleTypeDef hi2c1;

static SHT3X_Handle s_sensor = {
  .hi2c = &hi2c1,
  .address_7bit = SHT3X_I2C_ADDRESS_PRIMARY_7BIT,
  .timeout_ms = BOARD_TEMPERATURE_I2C_TIMEOUT_MS
};

static uint8_t s_present;

static BoardTemperature_Status board_temperature_from_sht3x(SHT3X_Status status);

BoardTemperature_Status BoardTemperature_Init(void)
{
  SHT3X_Status status;

  status = SHT3X_Init(&s_sensor);
  s_present = (status == SHT3X_OK) ? 1u : 0u;
  if (s_present == 0u)
  {
    return BOARD_TEMPERATURE_NOT_PRESENT;
  }

  return BOARD_TEMPERATURE_OK;
}

BoardTemperature_Status BoardTemperature_Read(BoardTemperature_Sample *sample)
{
  SHT3X_Sample sensor_sample;
  SHT3X_Status status;

  if (sample == NULL)
  {
    return BOARD_TEMPERATURE_INVALID_PARAM;
  }

  sample->temperature_c = 0.0f;
  sample->humidity_percent = 0.0f;
  sample->present = s_present;

  if (s_present == 0u)
  {
    return BOARD_TEMPERATURE_NOT_PRESENT;
  }

  status = SHT3X_Read(&s_sensor, &sensor_sample);
  if (status != SHT3X_OK)
  {
    return board_temperature_from_sht3x(status);
  }

  sample->temperature_c = sensor_sample.temperature_c;
  sample->humidity_percent = sensor_sample.humidity_percent;
  sample->present = 1u;

  return BOARD_TEMPERATURE_OK;
}

uint8_t BoardTemperature_IsPresent(void)
{
  return s_present;
}

const char *BoardTemperature_StatusText(BoardTemperature_Status status)
{
  switch (status)
  {
    case BOARD_TEMPERATURE_OK:
      return "OK";
    case BOARD_TEMPERATURE_ERROR:
      return "ERROR";
    case BOARD_TEMPERATURE_TIMEOUT:
      return "TIMEOUT";
    case BOARD_TEMPERATURE_CRC_ERROR:
      return "CRC_ERROR";
    case BOARD_TEMPERATURE_INVALID_PARAM:
      return "INVALID_PARAM";
    case BOARD_TEMPERATURE_NOT_PRESENT:
      return "NOT_PRESENT";
    default:
      return "UNKNOWN";
  }
}

static BoardTemperature_Status board_temperature_from_sht3x(SHT3X_Status status)
{
  switch (status)
  {
    case SHT3X_OK:
      return BOARD_TEMPERATURE_OK;
    case SHT3X_TIMEOUT:
      return BOARD_TEMPERATURE_TIMEOUT;
    case SHT3X_CRC_ERROR:
      return BOARD_TEMPERATURE_CRC_ERROR;
    case SHT3X_INVALID_PARAM:
      return BOARD_TEMPERATURE_INVALID_PARAM;
    case SHT3X_ERROR:
    default:
      return BOARD_TEMPERATURE_ERROR;
  }
}
