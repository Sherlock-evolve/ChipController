/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_protocol.c
  * @brief   RS485 ASCII protocol for bring-up and control.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "board_protocol.h"
#include "board_output.h"
#include "board_temperature.h"
#include "board_uart.h"
#include "chip_measure.h"
#include "thermal_control.h"

#include <stdint.h>
#include <string.h>

#define BOARD_PROTOCOL_LINE_SIZE     96u
#define BOARD_PROTOCOL_RX_BUDGET     16u
#define BOARD_PROTOCOL_TIMEOUT_MS    100u

static char s_line[BOARD_PROTOCOL_LINE_SIZE];
static uint8_t s_line_len;

static void board_protocol_process_line(const char *line);
static void board_protocol_print_help(void);
static void board_protocol_print_temp(void);
static void board_protocol_print_control(void);
static void board_protocol_print_ids(void);
static void board_protocol_print_r42(void);
static int board_protocol_parse_i32(const char *text, int32_t *value);
static int32_t board_protocol_float_to_milli(float value);
static int32_t board_protocol_float_to_micro(float value);

void BoardProtocol_Init(void)
{
  s_line_len = 0u;
}

void BoardProtocol_Poll(void)
{
  uint8_t i;
  uint8_t byte;

  for (i = 0u; i < BOARD_PROTOCOL_RX_BUDGET; i++)
  {
    if (BoardUart_Read(BOARD_UART_PORT_RS485, &byte, 1u, 0u) != BOARD_UART_OK)
    {
      return;
    }

    if ((byte == '\r') || (byte == '\n'))
    {
      if (s_line_len > 0u)
      {
        s_line[s_line_len] = '\0';
        BoardUart_Printf(BOARD_UART_PORT_DEBUG, "RS485 RX: %s\r\n", s_line);
        board_protocol_process_line(s_line);
        s_line_len = 0u;
      }
    }
    else if (s_line_len < (BOARD_PROTOCOL_LINE_SIZE - 1u))
    {
      s_line[s_line_len] = (char)byte;
      s_line_len++;
    }
    else
    {
      s_line_len = 0u;
      BoardUart_WriteString(BOARD_UART_PORT_RS485, "ERR LINE_TOO_LONG\r\n", BOARD_PROTOCOL_TIMEOUT_MS);
    }
  }
}

static void board_protocol_process_line(const char *line)
{
  if ((line == NULL) || (line[0] == '\0'))
  {
    return;
  }

  if ((strcmp(line, "HELP") == 0) || (strcmp(line, "?") == 0))
  {
    board_protocol_print_help();
  }
  else if (strcmp(line, "PING") == 0)
  {
    BoardUart_WriteString(BOARD_UART_PORT_RS485, "OK PONG\r\n", BOARD_PROTOCOL_TIMEOUT_MS);
  }
  else if (strcmp(line, "ID?") == 0)
  {
    board_protocol_print_ids();
  }
  else if (strcmp(line, "TEMP?") == 0)
  {
    board_protocol_print_temp();
  }
  else if (strcmp(line, "ZERO") == 0)
  {
    ThermalControl_Status control_status = ThermalControl_Stop();
    BoardOutput_Status output_status = BoardOutput_SetZero();

    if ((control_status == THERMAL_CONTROL_OK) && (output_status == BOARD_OUTPUT_OK))
    {
      BoardUart_WriteString(BOARD_UART_PORT_RS485, "OK ZERO\r\n", BOARD_PROTOCOL_TIMEOUT_MS);
    }
    else
    {
      BoardUart_Printf(BOARD_UART_PORT_RS485,
                       "ERR ZERO control=%s output=%s\r\n",
                       ThermalControl_StatusText(control_status),
                       BoardOutput_StatusText(output_status));
    }
  }
  else if (strcmp(line, "R42?") == 0)
  {
    board_protocol_print_r42();
  }
  else if (strcmp(line, "TC?") == 0)
  {
    board_protocol_print_control();
  }
  else if (strcmp(line, "TC STOP") == 0)
  {
    ThermalControl_Status status = ThermalControl_Stop();
    BoardUart_Printf(BOARD_UART_PORT_RS485, "OK TC_STOP status=%s\r\n", ThermalControl_StatusText(status));
  }
  else if (strncmp(line, "TC CURRENT ", 11u) == 0)
  {
    int32_t current_ua = 0;

    if (board_protocol_parse_i32(&line[11], &current_ua) == 0)
    {
      BoardUart_WriteString(BOARD_UART_PORT_RS485, "ERR BAD_ARG\r\n", BOARD_PROTOCOL_TIMEOUT_MS);
      return;
    }

    ThermalControl_Status status = ThermalControl_SetTargetCurrent((float)current_ua / 1000000.0f);
    if (status == THERMAL_CONTROL_OK)
    {
      BoardUart_Printf(BOARD_UART_PORT_RS485, "OK TC_CURRENT target_uA=%ld\r\n", (long)current_ua);
    }
    else
    {
      BoardUart_Printf(BOARD_UART_PORT_RS485, "ERR TC_CURRENT status=%s\r\n", ThermalControl_StatusText(status));
    }
  }
  else if (strncmp(line, "TC TEMP ", 8u) == 0)
  {
    int32_t target_mc = 0;

    if (board_protocol_parse_i32(&line[8], &target_mc) == 0)
    {
      BoardUart_WriteString(BOARD_UART_PORT_RS485, "ERR BAD_ARG\r\n", BOARD_PROTOCOL_TIMEOUT_MS);
      return;
    }

    ThermalControl_Status status = ThermalControl_SetTargetTemperature((float)target_mc / 1000.0f);
    if (status == THERMAL_CONTROL_OK)
    {
      BoardUart_Printf(BOARD_UART_PORT_RS485, "OK TC_TEMP target_mC=%ld\r\n", (long)target_mc);
    }
    else
    {
      BoardUart_Printf(BOARD_UART_PORT_RS485, "ERR TC_TEMP status=%s\r\n", ThermalControl_StatusText(status));
    }
  }
  else
  {
    BoardUart_Printf(BOARD_UART_PORT_RS485, "ERR UNKNOWN cmd=%s\r\n", line);
  }
}

static void board_protocol_print_help(void)
{
  BoardUart_WriteString(BOARD_UART_PORT_RS485,
                        "OK HELP PING ID? TEMP? R42? ZERO TC? TC STOP TC CURRENT <uA> TC TEMP <mC>\r\n",
                        BOARD_PROTOCOL_TIMEOUT_MS);
}

static void board_protocol_print_temp(void)
{
  BoardTemperature_Sample sample;
  BoardTemperature_Status status;

  status = BoardTemperature_Read(&sample);
  if (status == BOARD_TEMPERATURE_OK)
  {
    BoardUart_Printf(BOARD_UART_PORT_RS485,
                     "OK TEMP temp_mC=%ld\r\n",
                     (long)board_protocol_float_to_milli(sample.temperature_c));
  }
  else
  {
    BoardUart_Printf(BOARD_UART_PORT_RS485,
                     "ERR TEMP status=%s\r\n",
                     BoardTemperature_StatusText(status));
  }
}

static void board_protocol_print_control(void)
{
  ThermalControl_Snapshot snapshot;

  ThermalControl_GetSnapshot(&snapshot);
  BoardUart_Printf(BOARD_UART_PORT_RS485,
                   "OK TC mode=%s enabled=%u fault=%u status=%s target_mC=%ld temp_mC=%ld error_mC=%ld target_uA=%ld integral_uA=%ld current_uA=%ld voltage_mV=%ld power_uW=%ld resistance_mOhm=%ld drive_mV=%ld\r\n",
                   ThermalControl_ModeText(snapshot.mode),
                   snapshot.enabled,
                   snapshot.faulted,
                   ThermalControl_StatusText(snapshot.status),
                   (long)board_protocol_float_to_milli(snapshot.target_temperature_c),
                   (long)board_protocol_float_to_milli(snapshot.measured_temperature_c),
                   (long)board_protocol_float_to_milli(snapshot.temperature_error_c),
                   (long)board_protocol_float_to_micro(snapshot.target_current_a),
                   (long)board_protocol_float_to_micro(snapshot.temperature_integral_a),
                   (long)board_protocol_float_to_micro(snapshot.measured_current_a),
                   (long)board_protocol_float_to_milli(snapshot.load_voltage_v),
                   (long)board_protocol_float_to_micro(snapshot.power_w),
                   (long)board_protocol_float_to_milli(snapshot.resistance_ohm),
                   (long)board_protocol_float_to_milli(snapshot.drive_voltage_v));
}

static void board_protocol_print_ids(void)
{
  uint8_t current_adc_id = 0u;
  uint8_t voltage_adc_id = 0u;
  ChipMeasure_Status status;

  status = ChipMeasure_ReadAdcIds(&current_adc_id, &voltage_adc_id);
  if (status == CHIP_MEASURE_OK)
  {
    BoardUart_Printf(BOARD_UART_PORT_RS485,
                     "OK ID current=0x%02X voltage=0x%02X\r\n",
                     current_adc_id,
                     voltage_adc_id);
  }
  else
  {
    BoardUart_Printf(BOARD_UART_PORT_RS485, "ERR ID status=%d\r\n", (int)status);
  }
}

static void board_protocol_print_r42(void)
{
  BoardOutput_R42SelfTestResult result;
  BoardOutput_Status status;

  (void)ThermalControl_Stop();
  status = BoardOutput_RunR42SelfTest(&result);

  BoardUart_Printf(BOARD_UART_PORT_RS485,
                   "%s R42 status=%s pass=%u drive_mV=%ld current_uA=%ld voltage_mV=%ld resistance_mOhm=%ld\r\n",
                   (status == BOARD_OUTPUT_OK) ? "OK" : "ERR",
                   BoardOutput_StatusText(status),
                   result.passed,
                   (long)board_protocol_float_to_milli(result.applied_drive_v),
                   (long)board_protocol_float_to_micro(result.current_a),
                   (long)board_protocol_float_to_milli(result.load_voltage_v),
                   (long)board_protocol_float_to_milli(result.resistance_ohm));
}

static int board_protocol_parse_i32(const char *text, int32_t *value)
{
  int32_t sign = 1;
  int32_t result = 0;
  uint8_t saw_digit = 0u;

  if ((text == NULL) || (value == NULL))
  {
    return 0;
  }

  while (*text == ' ')
  {
    text++;
  }

  if (*text == '-')
  {
    sign = -1;
    text++;
  }
  else if (*text == '+')
  {
    text++;
  }

  while ((*text >= '0') && (*text <= '9'))
  {
    saw_digit = 1u;
    result = (result * 10) + (int32_t)(*text - '0');
    text++;
  }

  while (*text == ' ')
  {
    text++;
  }

  if ((*text != '\0') || (saw_digit == 0u))
  {
    return 0;
  }

  *value = result * sign;
  return 1;
}

static int32_t board_protocol_float_to_milli(float value)
{
  if (value >= 0.0f)
  {
    return (int32_t)((value * 1000.0f) + 0.5f);
  }

  return (int32_t)((value * 1000.0f) - 0.5f);
}

static int32_t board_protocol_float_to_micro(float value)
{
  if (value >= 0.0f)
  {
    return (int32_t)((value * 1000000.0f) + 0.5f);
  }

  return (int32_t)((value * 1000000.0f) - 0.5f);
}
