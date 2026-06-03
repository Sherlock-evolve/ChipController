/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    ad7190.c
  * @brief   AD7190 24-bit sigma-delta ADC driver.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "ad7190.h"

#define AD7190_REG_STATUS      0u
#define AD7190_REG_MODE        1u
#define AD7190_REG_CONFIG      2u
#define AD7190_REG_DATA        3u
#define AD7190_REG_ID          4u
#define AD7190_COMM_READ       0x40u
#define AD7190_COMM_WRITE      0x00u

#define AD7190_STATUS_RDY      0x80u
#define AD7190_STATUS_ERR      0x40u
#define AD7190_STATUS_NOREF    0x20u

#define AD7190_MODE_INTERNAL_CLOCK  (2u << 18)
#define AD7190_MODE_SINGLE          (1u << 21)
#define AD7190_MODE_FS_16HZ         96u

#define AD7190_CONFIG_CHOP          (1u << 23)
#define AD7190_CONFIG_REFDET        (1u << 6)
#define AD7190_CONFIG_BUF           (1u << 4)
#define AD7190_CONFIG_UNIPOLAR      (1u << 3)

static AD7190_Status ad7190_read_register(AD7190_Handle *adc,
                                          uint8_t reg,
                                          uint8_t *data,
                                          uint8_t len);
static AD7190_Status ad7190_write_register(AD7190_Handle *adc,
                                           uint8_t reg,
                                           uint32_t value,
                                           uint8_t len);
static AD7190_Status ad7190_write_mode(AD7190_Handle *adc, uint32_t mode);
static AD7190_Status ad7190_wait_ready(AD7190_Handle *adc, uint8_t *status);
static uint8_t ad7190_gain_value(AD7190_Gain gain);

AD7190_Status AD7190_Init(AD7190_Handle *adc)
{
  uint8_t id = 0u;
  AD7190_Status status;

  if ((adc == NULL) || (adc->hspi == NULL))
  {
    return AD7190_INVALID_PARAM;
  }

  if ((adc->sync_port != NULL) && (adc->sync_pin != 0u))
  {
    HAL_GPIO_WritePin(adc->sync_port, adc->sync_pin, GPIO_PIN_SET);
  }

  status = AD7190_Reset(adc);
  if (status != AD7190_OK)
  {
    return status;
  }

  HAL_Delay(1u);

  status = AD7190_ReadId(adc, &id);
  if (status != AD7190_OK)
  {
    return status;
  }

  if ((id & 0x0Fu) != 0x04u)
  {
    return AD7190_BAD_ID;
  }

  return AD7190_OK;
}

AD7190_Status AD7190_Reset(AD7190_Handle *adc)
{
  uint8_t reset_bytes[6] = {0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu, 0xFFu};

  if ((adc == NULL) || (adc->hspi == NULL))
  {
    return AD7190_INVALID_PARAM;
  }

  if (HAL_SPI_Transmit(adc->hspi, reset_bytes, sizeof(reset_bytes), adc->timeout_ms) != HAL_OK)
  {
    return AD7190_ERROR;
  }

  return AD7190_OK;
}

AD7190_Status AD7190_ReadId(AD7190_Handle *adc, uint8_t *id)
{
  if (id == NULL)
  {
    return AD7190_INVALID_PARAM;
  }

  return ad7190_read_register(adc, AD7190_REG_ID, id, 1u);
}

AD7190_Status AD7190_ReadStatus(AD7190_Handle *adc, uint8_t *status)
{
  if (status == NULL)
  {
    return AD7190_INVALID_PARAM;
  }

  return ad7190_read_register(adc, AD7190_REG_STATUS, status, 1u);
}

AD7190_Status AD7190_Configure(AD7190_Handle *adc,
                               uint8_t channels,
                               AD7190_Gain gain,
                               uint8_t bipolar,
                               uint8_t buffer_enabled,
                               uint8_t chop_enabled)
{
  uint32_t config;

  if ((adc == NULL) || (adc->hspi == NULL) || (channels == 0u))
  {
    return AD7190_INVALID_PARAM;
  }

  config = ((uint32_t)channels << 8);
  config |= AD7190_CONFIG_REFDET;

  if (chop_enabled != 0u)
  {
    config |= AD7190_CONFIG_CHOP;
  }

  if (buffer_enabled != 0u)
  {
    config |= AD7190_CONFIG_BUF;
  }

  if (bipolar == 0u)
  {
    config |= AD7190_CONFIG_UNIPOLAR;
  }

  config |= (uint32_t)gain & 0x07u;

  adc->gain = gain;

  return ad7190_write_register(adc, AD7190_REG_CONFIG, config, 3u);
}

AD7190_Status AD7190_ReadSingle(AD7190_Handle *adc, AD7190_Reading *reading)
{
  uint8_t data[3] = {0u};
  uint8_t status = 0u;
  uint32_t raw;
  AD7190_Status result;

  if ((adc == NULL) || (reading == NULL))
  {
    return AD7190_INVALID_PARAM;
  }

  result = ad7190_write_mode(adc, AD7190_MODE_SINGLE | AD7190_MODE_INTERNAL_CLOCK | AD7190_MODE_FS_16HZ);
  if (result != AD7190_OK)
  {
    return result;
  }

  result = ad7190_wait_ready(adc, &status);
  if (result != AD7190_OK)
  {
    return result;
  }

  result = ad7190_read_register(adc, AD7190_REG_DATA, data, 3u);
  if (result != AD7190_OK)
  {
    return result;
  }

  raw = ((uint32_t)data[0] << 16) | ((uint32_t)data[1] << 8) | (uint32_t)data[2];

  reading->raw_code = raw;
  reading->signed_code = (int32_t)raw - 0x800000;
  reading->status = status;
  reading->voltage = AD7190_ConvertBipolarCode(raw, adc->vref_volts, adc->gain);

  return AD7190_OK;
}

float AD7190_ConvertBipolarCode(uint32_t raw_code, float vref_volts, AD7190_Gain gain)
{
  int32_t signed_code = (int32_t)(raw_code & 0x00FFFFFFu) - 0x800000;
  float full_scale = vref_volts / (float)ad7190_gain_value(gain);

  return ((float)signed_code / 8388608.0f) * full_scale;
}

static AD7190_Status ad7190_read_register(AD7190_Handle *adc,
                                          uint8_t reg,
                                          uint8_t *data,
                                          uint8_t len)
{
  uint8_t command;
  uint8_t tx[5] = {0u, 0u, 0u, 0u, 0u};
  uint8_t rx[5] = {0u, 0u, 0u, 0u, 0u};
  uint8_t index;

  if ((adc == NULL) || (adc->hspi == NULL) || (data == NULL) || (len == 0u) || (len > 4u))
  {
    return AD7190_INVALID_PARAM;
  }

  command = AD7190_COMM_READ | ((reg & 0x07u) << 3);
  tx[0] = command;

  if (HAL_SPI_TransmitReceive(adc->hspi, tx, rx, (uint16_t)(len + 1u), adc->timeout_ms) != HAL_OK)
  {
    return AD7190_ERROR;
  }

  for (index = 0u; index < len; index++)
  {
    data[index] = rx[index + 1u];
  }

  return AD7190_OK;
}

static AD7190_Status ad7190_write_register(AD7190_Handle *adc,
                                           uint8_t reg,
                                           uint32_t value,
                                           uint8_t len)
{
  uint8_t tx[4];
  uint8_t index;

  if ((adc == NULL) || (adc->hspi == NULL) || (len == 0u) || (len > 3u))
  {
    return AD7190_INVALID_PARAM;
  }

  tx[0] = AD7190_COMM_WRITE | ((reg & 0x07u) << 3);

  for (index = 0u; index < len; index++)
  {
    tx[index + 1u] = (uint8_t)(value >> (8u * (len - 1u - index)));
  }

  if (HAL_SPI_Transmit(adc->hspi, tx, (uint16_t)(len + 1u), adc->timeout_ms) != HAL_OK)
  {
    return AD7190_ERROR;
  }

  return AD7190_OK;
}

static AD7190_Status ad7190_write_mode(AD7190_Handle *adc, uint32_t mode)
{
  return ad7190_write_register(adc, AD7190_REG_MODE, mode, 3u);
}

static AD7190_Status ad7190_wait_ready(AD7190_Handle *adc, uint8_t *status)
{
  uint32_t start;
  AD7190_Status result;

  if ((adc == NULL) || (status == NULL))
  {
    return AD7190_INVALID_PARAM;
  }

  start = HAL_GetTick();

  do
  {
    result = AD7190_ReadStatus(adc, status);
    if (result != AD7190_OK)
    {
      return result;
    }

    if ((*status & AD7190_STATUS_RDY) == 0u)
    {
      if ((*status & (AD7190_STATUS_ERR | AD7190_STATUS_NOREF)) != 0u)
      {
        return AD7190_ERROR;
      }

      return AD7190_OK;
    }
  } while ((HAL_GetTick() - start) < adc->timeout_ms);

  return AD7190_TIMEOUT;
}

static uint8_t ad7190_gain_value(AD7190_Gain gain)
{
  switch (gain)
  {
    case AD7190_GAIN_1:
      return 1u;
    case AD7190_GAIN_8:
      return 8u;
    case AD7190_GAIN_16:
      return 16u;
    case AD7190_GAIN_32:
      return 32u;
    case AD7190_GAIN_64:
      return 64u;
    case AD7190_GAIN_128:
      return 128u;
    default:
      return 1u;
  }
}
