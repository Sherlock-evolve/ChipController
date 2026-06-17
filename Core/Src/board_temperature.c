/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_temperature.c
  * @brief   Optional board temperature sensor wrapper.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "board_temperature.h"
#include "board_uart.h"

#define BOARD_TEMPERATURE_I2C_TIMEOUT_MS 100u
#define BOARD_TEMPERATURE_EXTERNAL_ENABLED 1u

#define BOARD_TEMPERATURE_EXT_TIMEOUT_MS 200u
#define BOARD_TEMPERATURE_EXT_ADDR 0xA5u
#define BOARD_TEMPERATURE_EXT_TYPE_READ 0x51u
#define BOARD_TEMPERATURE_EXT_TYPE_READ_REPLY 0x61u
#define BOARD_TEMPERATURE_EXT_STATUS_REQ 0xFFu
#define BOARD_TEMPERATURE_EXT_STATUS_OK 0x00u
#define BOARD_TEMPERATURE_EXT_CMD_CHIP 0x1Eu
#define BOARD_TEMPERATURE_EXT_CMD_STAGE 0x1Fu
#define BOARD_TEMPERATURE_EXT_MAX_FRAME 32u
#define BOARD_TEMPERATURE_EXT_TEMP_SCALE_C_PER_COUNT 1.0f

extern I2C_HandleTypeDef hi2c1;

static SHT3X_Handle s_sensor = {
  .hi2c = &hi2c1,
  .address_7bit = SHT3X_I2C_ADDRESS_PRIMARY_7BIT,
  .timeout_ms = BOARD_TEMPERATURE_I2C_TIMEOUT_MS
};

static uint8_t s_present;
static uint8_t s_external_enabled = BOARD_TEMPERATURE_EXTERNAL_ENABLED;

static BoardTemperature_Status board_temperature_from_sht3x(SHT3X_Status status);
static BoardTemperature_Status board_temperature_read_external(uint8_t command,
                                                               BoardTemperature_Sample *sample);
static void board_temperature_flush_external_rx(void);
static uint16_t board_temperature_crc16_modbus(const uint8_t *data, uint16_t len);

BoardTemperature_Status BoardTemperature_Init(void)
{
  SHT3X_Status status;

  status = SHT3X_Init(&s_sensor);
  s_present = (status == SHT3X_OK) ? 1u : 0u;
  if ((s_present == 0u) && (s_external_enabled == 0u))
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
    if (s_external_enabled != 0u)
    {
      return board_temperature_read_external(BOARD_TEMPERATURE_EXT_CMD_CHIP, sample);
    }

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

BoardTemperature_Status BoardTemperature_ReadStage(BoardTemperature_Sample *sample)
{
  if (sample == NULL)
  {
    return BOARD_TEMPERATURE_INVALID_PARAM;
  }

  sample->temperature_c = 0.0f;
  sample->humidity_percent = 0.0f;
  sample->present = 0u;

  if (s_external_enabled == 0u)
  {
    return BOARD_TEMPERATURE_NOT_PRESENT;
  }

  return board_temperature_read_external(BOARD_TEMPERATURE_EXT_CMD_STAGE, sample);
}

uint8_t BoardTemperature_IsPresent(void)
{
  return (s_present != 0u) || (s_external_enabled != 0u);
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

static BoardTemperature_Status board_temperature_read_external(uint8_t command,
                                                               BoardTemperature_Sample *sample)
{
  uint8_t request[13u];
  uint8_t response[BOARD_TEMPERATURE_EXT_MAX_FRAME];
  uint16_t response_len = 0u;
  uint16_t payload_len = 0u;
  uint16_t total_len = 0u;
  uint16_t crc = 0u;
  uint32_t start_tick = 0u;

  if (sample == NULL)
  {
    return BOARD_TEMPERATURE_INVALID_PARAM;
  }

  request[0] = 0x5Au;
  request[1] = BOARD_TEMPERATURE_EXT_ADDR;
  request[2] = BOARD_TEMPERATURE_EXT_TYPE_READ;
  request[3] = command;
  request[4] = 0x00u;
  request[5] = BOARD_TEMPERATURE_EXT_STATUS_REQ;
  request[6] = 0x01u;
  request[7] = 0x00u;
  request[8] = 0x00u;
  crc = board_temperature_crc16_modbus(&request[1], 8u);
  request[9] = (uint8_t)(crc & 0xFFu);
  request[10] = (uint8_t)((crc >> 8) & 0xFFu);
  request[11] = 0x0Du;
  request[12] = 0x0Au;

  board_temperature_flush_external_rx();
  if (BoardUart_Write(BOARD_UART_PORT_RS485, request, sizeof(request), BOARD_TEMPERATURE_EXT_TIMEOUT_MS) != BOARD_UART_OK)
  {
    return BOARD_TEMPERATURE_TIMEOUT;
  }

  start_tick = HAL_GetTick();
  while ((HAL_GetTick() - start_tick) < BOARD_TEMPERATURE_EXT_TIMEOUT_MS)
  {
    uint8_t byte = 0u;

    if (BoardUart_Read(BOARD_UART_PORT_RS485, &byte, 1u, 5u) != BOARD_UART_OK)
    {
      continue;
    }

    if ((response_len == 0u) && (byte != 0xAAu))
    {
      continue;
    }

    if (response_len >= sizeof(response))
    {
      return BOARD_TEMPERATURE_ERROR;
    }

    response[response_len] = byte;
    response_len++;

    if (response_len >= 8u)
    {
      payload_len = (uint16_t)response[6] | ((uint16_t)response[7] << 8);
      total_len = (uint16_t)(payload_len + 12u);
      if (total_len > sizeof(response))
      {
        return BOARD_TEMPERATURE_ERROR;
      }

      if (response_len >= total_len)
      {
        break;
      }
    }
  }

  if ((total_len == 0u) || (response_len < total_len))
  {
    return BOARD_TEMPERATURE_TIMEOUT;
  }

  if ((response[total_len - 2u] != 0x0Du) || (response[total_len - 1u] != 0x0Au))
  {
    return BOARD_TEMPERATURE_ERROR;
  }

  if ((response[1] != BOARD_TEMPERATURE_EXT_ADDR) ||
      (response[2] != BOARD_TEMPERATURE_EXT_TYPE_READ_REPLY) ||
      (response[3] != command) ||
      (response[4] != 0x00u))
  {
    return BOARD_TEMPERATURE_ERROR;
  }

  if (response[5] != BOARD_TEMPERATURE_EXT_STATUS_OK)
  {
    return BOARD_TEMPERATURE_ERROR;
  }

  if (payload_len < 2u)
  {
    return BOARD_TEMPERATURE_ERROR;
  }

  crc = (uint16_t)response[8u + payload_len] | ((uint16_t)response[9u + payload_len] << 8);
  if ((crc != 0u) &&
      (crc != board_temperature_crc16_modbus(&response[1], (uint16_t)(7u + payload_len))))
  {
    return BOARD_TEMPERATURE_CRC_ERROR;
  }

  {
    int16_t raw_temperature = (int16_t)((uint16_t)response[8] | ((uint16_t)response[9] << 8));

    sample->temperature_c = (float)raw_temperature * BOARD_TEMPERATURE_EXT_TEMP_SCALE_C_PER_COUNT;
    sample->humidity_percent = 0.0f;
    sample->present = 1u;
  }

  return BOARD_TEMPERATURE_OK;
}

static void board_temperature_flush_external_rx(void)
{
  uint8_t byte = 0u;
  uint8_t i;

  for (i = 0u; i < 32u; i++)
  {
    if (BoardUart_Read(BOARD_UART_PORT_RS485, &byte, 1u, 0u) != BOARD_UART_OK)
    {
      return;
    }
  }
}

static uint16_t board_temperature_crc16_modbus(const uint8_t *data, uint16_t len)
{
  uint16_t crc = 0xFFFFu;
  uint16_t i;

  if (data == NULL)
  {
    return 0u;
  }

  for (i = 0u; i < len; i++)
  {
    uint8_t bit;

    crc ^= data[i];
    for (bit = 0u; bit < 8u; bit++)
    {
      if ((crc & 0x0001u) != 0u)
      {
        crc = (uint16_t)((crc >> 1) ^ 0xA001u);
      }
      else
      {
        crc >>= 1;
      }
    }
  }

  return crc;
}
