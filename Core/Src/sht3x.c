/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    sht3x.c
  * @brief   Sensirion SHT3x temperature/humidity I2C driver.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "sht3x.h"

#define SHT3X_CMD_MEASURE_HIGH_REPEATABILITY 0x2400u
#define SHT3X_CMD_SOFT_RESET                 0x30A2u
#define SHT3X_MEASUREMENT_DELAY_MS           16u

static SHT3X_Status sht3x_write_command(SHT3X_Handle *sensor, uint16_t command);
static SHT3X_Status sht3x_from_hal(HAL_StatusTypeDef status);
static uint8_t sht3x_crc8(const uint8_t *data, uint8_t len);

SHT3X_Status SHT3X_Init(SHT3X_Handle *sensor)
{
  if ((sensor == NULL) || (sensor->hi2c == NULL) || (sensor->address_7bit > 0x7Fu))
  {
    return SHT3X_INVALID_PARAM;
  }

  return sht3x_from_hal(HAL_I2C_IsDeviceReady(sensor->hi2c,
                                              (uint16_t)sensor->address_7bit << 1,
                                              2u,
                                              sensor->timeout_ms));
}

SHT3X_Status SHT3X_Read(SHT3X_Handle *sensor, SHT3X_Sample *sample)
{
  uint8_t rx[6];
  uint16_t raw_temperature;
  uint16_t raw_humidity;
  SHT3X_Status status;

  if ((sensor == NULL) || (sample == NULL))
  {
    return SHT3X_INVALID_PARAM;
  }

  status = sht3x_write_command(sensor, SHT3X_CMD_MEASURE_HIGH_REPEATABILITY);
  if (status != SHT3X_OK)
  {
    return status;
  }

  HAL_Delay(SHT3X_MEASUREMENT_DELAY_MS);

  status = sht3x_from_hal(HAL_I2C_Master_Receive(sensor->hi2c,
                                                 (uint16_t)sensor->address_7bit << 1,
                                                 rx,
                                                 sizeof(rx),
                                                 sensor->timeout_ms));
  if (status != SHT3X_OK)
  {
    return status;
  }

  if ((sht3x_crc8(&rx[0], 2u) != rx[2]) || (sht3x_crc8(&rx[3], 2u) != rx[5]))
  {
    return SHT3X_CRC_ERROR;
  }

  raw_temperature = ((uint16_t)rx[0] << 8) | rx[1];
  raw_humidity = ((uint16_t)rx[3] << 8) | rx[4];

  sample->temperature_c = -45.0f + (175.0f * (float)raw_temperature / 65535.0f);
  sample->humidity_percent = 100.0f * (float)raw_humidity / 65535.0f;

  return SHT3X_OK;
}

SHT3X_Status SHT3X_SoftReset(SHT3X_Handle *sensor)
{
  SHT3X_Status status;

  status = sht3x_write_command(sensor, SHT3X_CMD_SOFT_RESET);
  if (status == SHT3X_OK)
  {
    HAL_Delay(2u);
  }

  return status;
}

const char *SHT3X_StatusText(SHT3X_Status status)
{
  switch (status)
  {
    case SHT3X_OK:
      return "OK";
    case SHT3X_ERROR:
      return "ERROR";
    case SHT3X_TIMEOUT:
      return "TIMEOUT";
    case SHT3X_CRC_ERROR:
      return "CRC_ERROR";
    case SHT3X_INVALID_PARAM:
      return "INVALID_PARAM";
    default:
      return "UNKNOWN";
  }
}

static SHT3X_Status sht3x_write_command(SHT3X_Handle *sensor, uint16_t command)
{
  uint8_t tx[2];

  if ((sensor == NULL) || (sensor->hi2c == NULL))
  {
    return SHT3X_INVALID_PARAM;
  }

  tx[0] = (uint8_t)(command >> 8);
  tx[1] = (uint8_t)command;

  return sht3x_from_hal(HAL_I2C_Master_Transmit(sensor->hi2c,
                                                (uint16_t)sensor->address_7bit << 1,
                                                tx,
                                                sizeof(tx),
                                                sensor->timeout_ms));
}

static SHT3X_Status sht3x_from_hal(HAL_StatusTypeDef status)
{
  switch (status)
  {
    case HAL_OK:
      return SHT3X_OK;
    case HAL_TIMEOUT:
      return SHT3X_TIMEOUT;
    case HAL_ERROR:
    case HAL_BUSY:
    default:
      return SHT3X_ERROR;
  }
}

static uint8_t sht3x_crc8(const uint8_t *data, uint8_t len)
{
  uint8_t crc = 0xFFu;
  uint8_t i;
  uint8_t bit;

  for (i = 0u; i < len; i++)
  {
    crc ^= data[i];
    for (bit = 0u; bit < 8u; bit++)
    {
      if ((crc & 0x80u) != 0u)
      {
        crc = (uint8_t)((crc << 1) ^ 0x31u);
      }
      else
      {
        crc <<= 1;
      }
    }
  }

  return crc;
}
