/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    ad5667.c
  * @brief   AD5667R dual 16-bit I2C DAC driver.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "ad5667.h"

#define AD5667_CMD_WRITE_INPUT          0x00u
#define AD5667_CMD_WRITE_UPDATE_ALL     0x10u
#define AD5667_CMD_WRITE_UPDATE_CHANNEL 0x18u
#define AD5667_CMD_INTERNAL_REFERENCE   0x38u

static AD5667_Status ad5667_write24(AD5667_Handle *dac, uint8_t command, uint16_t data);
static AD5667_Status ad5667_from_hal(HAL_StatusTypeDef status);

AD5667_Status AD5667_Init(AD5667_Handle *dac)
{
  AD5667_Status status;

  if ((dac == NULL) || (dac->hi2c == NULL) || (dac->address_7bit > 0x7Fu) ||
      (dac->full_scale_volts <= 0.0f))
  {
    return AD5667_INVALID_PARAM;
  }

  status = ad5667_write24(dac, AD5667_CMD_INTERNAL_REFERENCE, 0x0001u);
  if (status != AD5667_OK)
  {
    return status;
  }

  return AD5667_ClearToZero(dac);
}

AD5667_Status AD5667_SetVoltage(AD5667_Handle *dac, AD5667_Channel channel, float volts)
{
  if (dac == NULL)
  {
    return AD5667_INVALID_PARAM;
  }

  return AD5667_SetCode(dac, channel, AD5667_VoltsToCode(dac, volts));
}

AD5667_Status AD5667_SetCode(AD5667_Handle *dac, AD5667_Channel channel, uint16_t code)
{
  uint8_t command;

  if ((dac == NULL) || (dac->hi2c == NULL))
  {
    return AD5667_INVALID_PARAM;
  }

  if ((channel != AD5667_CHANNEL_A) && (channel != AD5667_CHANNEL_B) && (channel != AD5667_CHANNEL_BOTH))
  {
    return AD5667_INVALID_PARAM;
  }

  command = AD5667_CMD_WRITE_UPDATE_CHANNEL | ((uint8_t)channel & 0x07u);
  return ad5667_write24(dac, command, code);
}

AD5667_Status AD5667_SetBothVoltage(AD5667_Handle *dac, float volts)
{
  return AD5667_SetVoltage(dac, AD5667_CHANNEL_BOTH, volts);
}

AD5667_Status AD5667_ClearToZero(AD5667_Handle *dac)
{
  return AD5667_SetCode(dac, AD5667_CHANNEL_BOTH, 0u);
}

uint16_t AD5667_VoltsToCode(AD5667_Handle *dac, float volts)
{
  float clamped;
  uint32_t code;

  if ((dac == NULL) || (dac->full_scale_volts <= 0.0f))
  {
    return 0u;
  }

  clamped = volts;
  if (clamped < 0.0f)
  {
    clamped = 0.0f;
  }
  else if (clamped > dac->full_scale_volts)
  {
    clamped = dac->full_scale_volts;
  }

  code = (uint32_t)((clamped * 65535.0f / dac->full_scale_volts) + 0.5f);
  if (code > 0xFFFFu)
  {
    code = 0xFFFFu;
  }

  return (uint16_t)code;
}

static AD5667_Status ad5667_write24(AD5667_Handle *dac, uint8_t command, uint16_t data)
{
  uint8_t tx[3];
  uint16_t device_address;

  if ((dac == NULL) || (dac->hi2c == NULL))
  {
    return AD5667_INVALID_PARAM;
  }

  tx[0] = command;
  tx[1] = (uint8_t)(data >> 8);
  tx[2] = (uint8_t)data;
  device_address = (uint16_t)dac->address_7bit << 1;

  return ad5667_from_hal(HAL_I2C_Master_Transmit(dac->hi2c, device_address, tx, sizeof(tx), dac->timeout_ms));
}

static AD5667_Status ad5667_from_hal(HAL_StatusTypeDef status)
{
  switch (status)
  {
    case HAL_OK:
      return AD5667_OK;
    case HAL_TIMEOUT:
      return AD5667_TIMEOUT;
    case HAL_ERROR:
    case HAL_BUSY:
    default:
      return AD5667_ERROR;
  }
}
