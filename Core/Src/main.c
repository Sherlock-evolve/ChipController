/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "board_uart.h"
#include "board_output.h"
#include "board_protocol.h"
#include "board_temperature.h"
#include "chip_measure.h"
#include "thermal_control.h"
#include <string.h>

/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define APP_DEBUG_LINE_SIZE 64u

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

I2C_HandleTypeDef hi2c1;

SPI_HandleTypeDef hspi1;
SPI_HandleTypeDef hspi2;

TIM_HandleTypeDef htim1;
TIM_HandleTypeDef htim3;

UART_HandleTypeDef huart1;
UART_HandleTypeDef huart2;

/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);
static void MX_USART2_UART_Init(void);
static void MX_SPI1_Init(void);
static void MX_SPI2_Init(void);
static void MX_TIM1_Init(void);
static void MX_I2C1_Init(void);
static void MX_TIM3_Init(void);
/* USER CODE BEGIN PFP */
static void App_ProcessDebugLine(const char *line);
static void App_PrintHelp(void);
static void App_PrintTemperature(void);
static void App_PrintThermalControl(void);
static uint8_t App_ParseFloat(const char *text, float *value);
static int32_t App_FloatToMilli(float value);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static const char *App_ChipMeasureStatusText(ChipMeasure_Status status)
{
  switch (status)
  {
    case CHIP_MEASURE_OK:
      return "OK";
    case CHIP_MEASURE_ERROR:
      return "ERROR";
    case CHIP_MEASURE_TIMEOUT:
      return "TIMEOUT";
    case CHIP_MEASURE_BAD_ID:
      return "BAD_ID";
    case CHIP_MEASURE_INVALID_PARAM:
      return "INVALID_PARAM";
    case CHIP_MEASURE_NO_CURRENT:
      return "NO_CURRENT";
    default:
      return "UNKNOWN";
  }
}

static void App_ProcessDebugLine(const char *line)
{
  if ((line == NULL) || (line[0] == '\0'))
  {
    return;
  }

  if ((strcmp(line, "help") == 0) || (strcmp(line, "?") == 0))
  {
    App_PrintHelp();
  }
  else if (strcmp(line, "id") == 0)
  {
    uint8_t current_adc_id = 0u;
    uint8_t voltage_adc_id = 0u;
    ChipMeasure_Status status = ChipMeasure_ReadAdcIds(&current_adc_id, &voltage_adc_id);

    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "AD7190 IDs: current=0x%02X voltage=0x%02X status=%s (%d)\r\n",
                     current_adc_id,
                     voltage_adc_id,
                     App_ChipMeasureStatusText(status),
                     (int)status);
  }
  else if (strcmp(line, "zero") == 0)
  {
    ThermalControl_Status control_status = ThermalControl_Stop();
    BoardOutput_Status status = BoardOutput_SetZero();
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "Output zero: %s (%d), control=%s\r\n",
                     BoardOutput_StatusText(status),
                     (int)status,
                     ThermalControl_StatusText(control_status));
  }
  else if (strcmp(line, "r42test") == 0)
  {
    BoardOutput_R42SelfTestResult result;
    BoardOutput_Status status;

    (void)ThermalControl_Stop();
    BoardUart_WriteString(BOARD_UART_PORT_DEBUG, "R42 self-test running...\r\n", 100u);
    status = BoardOutput_RunR42SelfTest(&result);

    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "R42 self-test: %s (%d), pass=%u\r\n",
                     BoardOutput_StatusText(status),
                     (int)status,
                     result.passed);
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "drive=%ld mV, Isense=%ld uV, I=%ld uA\r\n",
                     (long)App_FloatToMilli(result.applied_drive_v),
                     (long)App_FloatToMilli(result.current_sense_v * 1000.0f),
                     (long)App_FloatToMilli(result.current_a * 1000.0f));
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "Vraw=%ld mV, Vload=%ld mV, R=%ld mOhm\r\n",
                     (long)App_FloatToMilli(result.load_voltage_raw_v),
                     (long)App_FloatToMilli(result.load_voltage_v),
                     (long)App_FloatToMilli(result.resistance_ohm));
  }
  else if (strcmp(line, "temp") == 0)
  {
    App_PrintTemperature();
  }
  else if (strcmp(line, "rs485 tx") == 0)
  {
    BoardUart_Status status;

    status = BoardUart_WriteString(BOARD_UART_PORT_RS485, "OK RS485_DEBUG_TX\r\n", 100u);
    BoardUart_Printf(BOARD_UART_PORT_DEBUG, "RS485 debug TX: %d\r\n", (int)status);
  }
  else if (strcmp(line, "tc status") == 0)
  {
    App_PrintThermalControl();
  }
  else if (strcmp(line, "tc stop") == 0)
  {
    ThermalControl_Status status = ThermalControl_Stop();

    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "ThermalControl stop: %s (%d)\r\n",
                     ThermalControl_StatusText(status),
                     (int)status);
    App_PrintThermalControl();
  }
  else if (strncmp(line, "tc current ", 11u) == 0)
  {
    float target_ma = 0.0f;

    if (App_ParseFloat(&line[11], &target_ma) == 0u)
    {
      BoardUart_WriteString(BOARD_UART_PORT_DEBUG, "Bad argument. Usage: tc current <mA>\r\n", 100u);
      return;
    }

    ThermalControl_Status status = ThermalControl_SetTargetCurrent(target_ma / 1000.0f);
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "ThermalControl current target: %ld uA, status=%s (%d)\r\n",
                     (long)App_FloatToMilli(target_ma),
                     ThermalControl_StatusText(status),
                     (int)status);
  }
  else if (strncmp(line, "tc temp ", 8u) == 0)
  {
    float target_c = 0.0f;

    if (App_ParseFloat(&line[8], &target_c) == 0u)
    {
      BoardUart_WriteString(BOARD_UART_PORT_DEBUG, "Bad argument. Usage: tc temp <degC>\r\n", 100u);
      return;
    }

    ThermalControl_Status status = ThermalControl_SetTargetTemperature(target_c);
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "ThermalControl temperature target: %ld mC, status=%s (%d)\r\n",
                     (long)App_FloatToMilli(target_c),
                     ThermalControl_StatusText(status),
                     (int)status);
  }
  else
  {
    BoardUart_Printf(BOARD_UART_PORT_DEBUG, "Unknown command: %s\r\n", line);
    App_PrintHelp();
  }
}

static void App_PrintHelp(void)
{
  BoardUart_WriteString(BOARD_UART_PORT_DEBUG,
                        "Commands:\r\n"
                        "  help     - show this help\r\n"
                        "  id       - read AD7190 IDs\r\n"
                        "  zero     - force DAC outputs to 0V\r\n"
                        "  r42test  - run safe internal 30-ohm self-test\r\n"
                        "  temp     - read optional SHT3x temperature sensor\r\n"
                        "  rs485 tx - send a test line on CN4 RS485\r\n"
                        "  tc status      - show control loop state\r\n"
                        "  tc stop        - stop control and zero output\r\n"
                        "  tc current <mA> - start current loop\r\n"
                        "  tc temp <degC>  - start temperature loop\r\n",
                        100u);
}

static void App_PrintTemperature(void)
{
  BoardTemperature_Sample sample;
  BoardTemperature_Status status;

  status = BoardTemperature_Read(&sample);
  if (status == BOARD_TEMPERATURE_OK)
  {
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "Temperature: %ld mC, humidity=%ld mpermil\r\n",
                     (long)App_FloatToMilli(sample.temperature_c),
                     (long)App_FloatToMilli(sample.humidity_percent));
  }
  else
  {
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "Temperature read: %s (%d)\r\n",
                     BoardTemperature_StatusText(status),
                     (int)status);
  }
}

static void App_PrintThermalControl(void)
{
  ThermalControl_Snapshot snapshot;

  ThermalControl_GetSnapshot(&snapshot);
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "TC: mode=%s enabled=%u fault=%u status=%s (%d)\r\n",
                   ThermalControl_ModeText(snapshot.mode),
                   snapshot.enabled,
                   snapshot.faulted,
                   ThermalControl_StatusText(snapshot.status),
                   (int)snapshot.status);
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "TC target: temp=%ld mC error=%ld mC current=%ld uA integral=%ld uA drive=%ld mV\r\n",
                   (long)App_FloatToMilli(snapshot.target_temperature_c),
                   (long)App_FloatToMilli(snapshot.temperature_error_c),
                   (long)App_FloatToMilli(snapshot.target_current_a * 1000.0f),
                   (long)App_FloatToMilli(snapshot.temperature_integral_a * 1000.0f),
                   (long)App_FloatToMilli(snapshot.drive_voltage_v));
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "TC measured: temp=%ld mC current=%ld uA voltage=%ld mV power=%ld uW R=%ld mOhm\r\n",
                   (long)App_FloatToMilli(snapshot.measured_temperature_c),
                   (long)App_FloatToMilli(snapshot.measured_current_a * 1000.0f),
                   (long)App_FloatToMilli(snapshot.load_voltage_v),
                   (long)App_FloatToMilli(snapshot.power_w * 1000.0f),
                   (long)App_FloatToMilli(snapshot.resistance_ohm));
}

static uint8_t App_ParseFloat(const char *text, float *value)
{
  float result = 0.0f;
  float scale = 0.1f;
  float sign = 1.0f;
  uint8_t saw_digit = 0u;

  if ((text == NULL) || (value == NULL))
  {
    return 0u;
  }

  while (*text == ' ')
  {
    text++;
  }

  if (*text == '-')
  {
    sign = -1.0f;
    text++;
  }
  else if (*text == '+')
  {
    text++;
  }

  while ((*text >= '0') && (*text <= '9'))
  {
    saw_digit = 1u;
    result = (result * 10.0f) + (float)(*text - '0');
    text++;
  }

  if (*text == '.')
  {
    text++;
    while ((*text >= '0') && (*text <= '9'))
    {
      saw_digit = 1u;
      result += (float)(*text - '0') * scale;
      scale *= 0.1f;
      text++;
    }
  }

  while (*text == ' ')
  {
    text++;
  }

  if ((*text != '\0') || (saw_digit == 0u))
  {
    return 0u;
  }

  *value = result * sign;
  return 1u;
}

static int32_t App_FloatToMilli(float value)
{
  if (value >= 0.0f)
  {
    return (int32_t)((value * 1000.0f) + 0.5f);
  }

  return (int32_t)((value * 1000.0f) - 0.5f);
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_USART1_UART_Init();
  MX_USART2_UART_Init();
  MX_SPI1_Init();
  MX_SPI2_Init();
  MX_TIM1_Init();
  MX_I2C1_Init();
  MX_TIM3_Init();
  /* USER CODE BEGIN 2 */
  BoardUart_Init(&huart2, &huart1);
  BoardUart_WriteString(BOARD_UART_PORT_DEBUG, "\r\nChipController boot\r\n", 100u);

  BoardOutput_Status output_status = BoardOutput_Init();
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "BoardOutput_Init: %s (%d)\r\n",
                   BoardOutput_StatusText(output_status),
                   (int)output_status);

  ChipMeasure_Status measure_status = ChipMeasure_Init();
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "ChipMeasure_Init: %s (%d)\r\n",
                   App_ChipMeasureStatusText(measure_status),
                   (int)measure_status);

  if (measure_status == CHIP_MEASURE_OK)
  {
    uint8_t current_adc_id = 0u;
    uint8_t voltage_adc_id = 0u;

    measure_status = ChipMeasure_ReadAdcIds(&current_adc_id, &voltage_adc_id);
    BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                     "AD7190 IDs: current=0x%02X voltage=0x%02X status=%s (%d)\r\n",
                     current_adc_id,
                     voltage_adc_id,
                     App_ChipMeasureStatusText(measure_status),
                     (int)measure_status);
  }

  BoardTemperature_Status temperature_status = BoardTemperature_Init();
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "BoardTemperature_Init: %s (%d)\r\n",
                   BoardTemperature_StatusText(temperature_status),
                   (int)temperature_status);

  ThermalControl_Status control_status = ThermalControl_Init();
  BoardUart_Printf(BOARD_UART_PORT_DEBUG,
                   "ThermalControl_Init: %s (%d)\r\n",
                   ThermalControl_StatusText(control_status),
                   (int)control_status);

  BoardProtocol_Init();
  App_PrintHelp();

  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    /* USER CODE END WHILE */

    /* USER CODE BEGIN 3 */
    static char debug_line[APP_DEBUG_LINE_SIZE];
    static uint8_t debug_line_len = 0u;
    uint8_t byte = 0u;

    if (BoardUart_Read(BOARD_UART_PORT_DEBUG, &byte, 1u, 0u) == BOARD_UART_OK)
    {
      if ((byte == '\r') || (byte == '\n'))
      {
        if (debug_line_len > 0u)
        {
          debug_line[debug_line_len] = '\0';
          BoardUart_WriteString(BOARD_UART_PORT_DEBUG, "\r\n", 100u);
          App_ProcessDebugLine(debug_line);
          debug_line_len = 0u;
        }
      }
      else if ((byte == '\b') || (byte == 0x7Fu))
      {
        if (debug_line_len > 0u)
        {
          debug_line_len--;
          BoardUart_WriteString(BOARD_UART_PORT_DEBUG, "\b \b", 100u);
        }
      }
      else if (debug_line_len < (APP_DEBUG_LINE_SIZE - 1u))
      {
        debug_line[debug_line_len] = (char)byte;
        debug_line_len++;
        BoardUart_Write(BOARD_UART_PORT_DEBUG, &byte, 1u, 100u);
      }
    }

    BoardProtocol_Poll();
    (void)ThermalControl_Service(HAL_GetTick());
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Supply configuration update enable
  */
  HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);

  /** Configure the main internal regulator output voltage
  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE0);

  while(!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 2;
  RCC_OscInitStruct.PLL.PLLN = 72;
  RCC_OscInitStruct.PLL.PLLP = 2;
  RCC_OscInitStruct.PLL.PLLQ = 18;
  RCC_OscInitStruct.PLL.PLLR = 2;
  RCC_OscInitStruct.PLL.PLLRGE = RCC_PLL1VCIRANGE_3;
  RCC_OscInitStruct.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE;
  RCC_OscInitStruct.PLL.PLLFRACN = 0;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2
                              |RCC_CLOCKTYPE_D3PCLK1|RCC_CLOCKTYPE_D1PCLK1;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.SYSCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_HCLK_DIV2;
  RCC_ClkInitStruct.APB3CLKDivider = RCC_APB3_DIV2;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_APB1_DIV2;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_APB2_DIV2;
  RCC_ClkInitStruct.APB4CLKDivider = RCC_APB4_DIV2;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_3) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief I2C1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_I2C1_Init(void)
{

  /* USER CODE BEGIN I2C1_Init 0 */

  /* USER CODE END I2C1_Init 0 */

  /* USER CODE BEGIN I2C1_Init 1 */

  /* USER CODE END I2C1_Init 1 */
  hi2c1.Instance = I2C1;
  hi2c1.Init.Timing = 0x209093DD;
  hi2c1.Init.OwnAddress1 = 0;
  hi2c1.Init.AddressingMode = I2C_ADDRESSINGMODE_7BIT;
  hi2c1.Init.DualAddressMode = I2C_DUALADDRESS_DISABLE;
  hi2c1.Init.OwnAddress2 = 0;
  hi2c1.Init.OwnAddress2Masks = I2C_OA2_NOMASK;
  hi2c1.Init.GeneralCallMode = I2C_GENERALCALL_DISABLE;
  hi2c1.Init.NoStretchMode = I2C_NOSTRETCH_DISABLE;
  if (HAL_I2C_Init(&hi2c1) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Analogue filter
  */
  if (HAL_I2CEx_ConfigAnalogFilter(&hi2c1, I2C_ANALOGFILTER_ENABLE) != HAL_OK)
  {
    Error_Handler();
  }

  /** Configure Digital filter
  */
  if (HAL_I2CEx_ConfigDigitalFilter(&hi2c1, 0) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN I2C1_Init 2 */

  /* USER CODE END I2C1_Init 2 */

}

/**
  * @brief SPI1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI1_Init(void)
{

  /* USER CODE BEGIN SPI1_Init 0 */

  /* USER CODE END SPI1_Init 0 */

  /* USER CODE BEGIN SPI1_Init 1 */

  /* USER CODE END SPI1_Init 1 */
  /* SPI1 parameter configuration*/
  hspi1.Instance = SPI1;
  hspi1.Init.Mode = SPI_MODE_MASTER;
  hspi1.Init.Direction = SPI_DIRECTION_2LINES;
  hspi1.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi1.Init.CLKPolarity = SPI_POLARITY_HIGH;
  hspi1.Init.CLKPhase = SPI_PHASE_2EDGE;
  hspi1.Init.NSS = SPI_NSS_HARD_OUTPUT;
  hspi1.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_256;
  hspi1.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi1.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi1.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi1.Init.CRCPolynomial = 0x0;
  hspi1.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  hspi1.Init.NSSPolarity = SPI_NSS_POLARITY_LOW;
  hspi1.Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
  hspi1.Init.TxCRCInitializationPattern = SPI_CRC_INITIALIZATION_ALL_ZERO_PATTERN;
  hspi1.Init.RxCRCInitializationPattern = SPI_CRC_INITIALIZATION_ALL_ZERO_PATTERN;
  hspi1.Init.MasterSSIdleness = SPI_MASTER_SS_IDLENESS_00CYCLE;
  hspi1.Init.MasterInterDataIdleness = SPI_MASTER_INTERDATA_IDLENESS_00CYCLE;
  hspi1.Init.MasterReceiverAutoSusp = SPI_MASTER_RX_AUTOSUSP_DISABLE;
  hspi1.Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_DISABLE;
  hspi1.Init.IOSwap = SPI_IO_SWAP_DISABLE;
  if (HAL_SPI_Init(&hspi1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI1_Init 2 */

  /* USER CODE END SPI1_Init 2 */

}

/**
  * @brief SPI2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_SPI2_Init(void)
{

  /* USER CODE BEGIN SPI2_Init 0 */

  /* USER CODE END SPI2_Init 0 */

  /* USER CODE BEGIN SPI2_Init 1 */

  /* USER CODE END SPI2_Init 1 */
  /* SPI2 parameter configuration*/
  hspi2.Instance = SPI2;
  hspi2.Init.Mode = SPI_MODE_MASTER;
  hspi2.Init.Direction = SPI_DIRECTION_2LINES;
  hspi2.Init.DataSize = SPI_DATASIZE_8BIT;
  hspi2.Init.CLKPolarity = SPI_POLARITY_HIGH;
  hspi2.Init.CLKPhase = SPI_PHASE_2EDGE;
  hspi2.Init.NSS = SPI_NSS_HARD_OUTPUT;
  hspi2.Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_256;
  hspi2.Init.FirstBit = SPI_FIRSTBIT_MSB;
  hspi2.Init.TIMode = SPI_TIMODE_DISABLE;
  hspi2.Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
  hspi2.Init.CRCPolynomial = 0x0;
  hspi2.Init.NSSPMode = SPI_NSS_PULSE_DISABLE;
  hspi2.Init.NSSPolarity = SPI_NSS_POLARITY_LOW;
  hspi2.Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
  hspi2.Init.TxCRCInitializationPattern = SPI_CRC_INITIALIZATION_ALL_ZERO_PATTERN;
  hspi2.Init.RxCRCInitializationPattern = SPI_CRC_INITIALIZATION_ALL_ZERO_PATTERN;
  hspi2.Init.MasterSSIdleness = SPI_MASTER_SS_IDLENESS_00CYCLE;
  hspi2.Init.MasterInterDataIdleness = SPI_MASTER_INTERDATA_IDLENESS_00CYCLE;
  hspi2.Init.MasterReceiverAutoSusp = SPI_MASTER_RX_AUTOSUSP_DISABLE;
  hspi2.Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_DISABLE;
  hspi2.Init.IOSwap = SPI_IO_SWAP_DISABLE;
  if (HAL_SPI_Init(&hspi2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN SPI2_Init 2 */

  /* USER CODE END SPI2_Init 2 */

}

/**
  * @brief TIM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM1_Init(void)
{

  /* USER CODE BEGIN TIM1_Init 0 */

  /* USER CODE END TIM1_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM1_Init 1 */

  /* USER CODE END TIM1_Init 1 */
  htim1.Instance = TIM1;
  htim1.Init.Prescaler = 9;
  htim1.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim1.Init.Period = 499;
  htim1.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim1.Init.RepetitionCounter = 0;
  htim1.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim1) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim1, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterOutputTrigger2 = TIM_TRGO2_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim1, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM1_Init 2 */

  /* USER CODE END TIM1_Init 2 */

}

/**
  * @brief TIM3 Initialization Function
  * @param None
  * @retval None
  */
static void MX_TIM3_Init(void)
{

  /* USER CODE BEGIN TIM3_Init 0 */

  /* USER CODE END TIM3_Init 0 */

  TIM_ClockConfigTypeDef sClockSourceConfig = {0};
  TIM_MasterConfigTypeDef sMasterConfig = {0};

  /* USER CODE BEGIN TIM3_Init 1 */

  /* USER CODE END TIM3_Init 1 */
  htim3.Instance = TIM3;
  htim3.Init.Prescaler = 44999;
  htim3.Init.CounterMode = TIM_COUNTERMODE_UP;
  htim3.Init.Period = 4999;
  htim3.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
  htim3.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
  if (HAL_TIM_Base_Init(&htim3) != HAL_OK)
  {
    Error_Handler();
  }
  sClockSourceConfig.ClockSource = TIM_CLOCKSOURCE_INTERNAL;
  if (HAL_TIM_ConfigClockSource(&htim3, &sClockSourceConfig) != HAL_OK)
  {
    Error_Handler();
  }
  sMasterConfig.MasterOutputTrigger = TIM_TRGO_RESET;
  sMasterConfig.MasterSlaveMode = TIM_MASTERSLAVEMODE_DISABLE;
  if (HAL_TIMEx_MasterConfigSynchronization(&htim3, &sMasterConfig) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN TIM3_Init 2 */

  /* USER CODE END TIM3_Init 2 */

}

/**
  * @brief USART1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART1_UART_Init(void)
{

  /* USER CODE BEGIN USART1_Init 0 */

  /* USER CODE END USART1_Init 0 */

  /* USER CODE BEGIN USART1_Init 1 */

  /* USER CODE END USART1_Init 1 */
  huart1.Instance = USART1;
  huart1.Init.BaudRate = 19200;
  huart1.Init.WordLength = UART_WORDLENGTH_8B;
  huart1.Init.StopBits = UART_STOPBITS_1;
  huart1.Init.Parity = UART_PARITY_NONE;
  huart1.Init.Mode = UART_MODE_TX_RX;
  huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart1.Init.OverSampling = UART_OVERSAMPLING_16;
  huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart1.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart1, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart1, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart1) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART1_Init 2 */

  /* USER CODE END USART1_Init 2 */

}

/**
  * @brief USART2 Initialization Function
  * @param None
  * @retval None
  */
static void MX_USART2_UART_Init(void)
{

  /* USER CODE BEGIN USART2_Init 0 */

  /* USER CODE END USART2_Init 0 */

  /* USER CODE BEGIN USART2_Init 1 */

  /* USER CODE END USART2_Init 1 */
  huart2.Instance = USART2;
  huart2.Init.BaudRate = 115200;
  huart2.Init.WordLength = UART_WORDLENGTH_8B;
  huart2.Init.StopBits = UART_STOPBITS_1;
  huart2.Init.Parity = UART_PARITY_NONE;
  huart2.Init.Mode = UART_MODE_TX_RX;
  huart2.Init.HwFlowCtl = UART_HWCONTROL_NONE;
  huart2.Init.OverSampling = UART_OVERSAMPLING_16;
  huart2.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
  huart2.Init.ClockPrescaler = UART_PRESCALER_DIV1;
  huart2.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;
  if (HAL_UART_Init(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetTxFifoThreshold(&huart2, UART_TXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_SetRxFifoThreshold(&huart2, UART_RXFIFO_THRESHOLD_1_8) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_UARTEx_DisableFifoMode(&huart2) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN USART2_Init 2 */

  /* USER CODE END USART2_Init 2 */

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOE_CLK_ENABLE();
  __HAL_RCC_GPIOI_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOG_CLK_ENABLE();
  __HAL_RCC_GPIOD_CLK_ENABLE();

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOA, Wakeup_Pin|RE485_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOB, LED0_Pin|LED1_Pin|DAC_ADDR_Pin|DAC_CLR_Pin
                          |DAC_LDAC_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOH, CHIP2_Pin|CHIP1_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pin Output Level */
  HAL_GPIO_WritePin(GPIOG, SPI2_SYNC_Pin|SPI1_SYNC_Pin, GPIO_PIN_RESET);

  /*Configure GPIO pins : PE2 PE3 PE4 PE5
                           PE6 PE7 PE8 PE9
                           PE10 PE11 PE12 PE13
                           PE14 PE15 PE0 PE1 */
  GPIO_InitStruct.Pin = GPIO_PIN_2|GPIO_PIN_3|GPIO_PIN_4|GPIO_PIN_5
                          |GPIO_PIN_6|GPIO_PIN_7|GPIO_PIN_8|GPIO_PIN_9
                          |GPIO_PIN_10|GPIO_PIN_11|GPIO_PIN_12|GPIO_PIN_13
                          |GPIO_PIN_14|GPIO_PIN_15|GPIO_PIN_0|GPIO_PIN_1;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  /*Configure GPIO pins : PI8 PI9 PI10 PI11
                           PI0 PI1 PI2 PI3
                           PI4 PI5 PI6 PI7 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11
                          |GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3
                          |GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_6|GPIO_PIN_7;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOI, &GPIO_InitStruct);

  /*Configure GPIO pins : PC13 PC0 PC3 PC4
                           PC5 PC6 PC7 PC8
                           PC9 PC10 PC11 PC12 */
  GPIO_InitStruct.Pin = GPIO_PIN_13|GPIO_PIN_0|GPIO_PIN_3|GPIO_PIN_4
                          |GPIO_PIN_5|GPIO_PIN_6|GPIO_PIN_7|GPIO_PIN_8
                          |GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11|GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

  /*Configure GPIO pins : PF0 PF1 PF2 PF3
                           PF4 PF5 PF6 PF7
                           PF8 PF9 PF10 PF11
                           PF12 PF13 PF14 PF15 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3
                          |GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_6|GPIO_PIN_7
                          |GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11
                          |GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOF, &GPIO_InitStruct);

  /*Configure GPIO pins : Wakeup_Pin RE485_Pin */
  GPIO_InitStruct.Pin = Wakeup_Pin|RE485_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : PA1 PA2 PA3 PA4
                           PA5 PA11 PA12 */
  GPIO_InitStruct.Pin = GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3|GPIO_PIN_4
                          |GPIO_PIN_5|GPIO_PIN_11|GPIO_PIN_12;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

  /*Configure GPIO pins : PH2 PH3 PH4 PH5
                           PH6 PH7 PH8 PH9
                           PH12 PH13 PH14 PH15 */
  GPIO_InitStruct.Pin = GPIO_PIN_2|GPIO_PIN_3|GPIO_PIN_4|GPIO_PIN_5
                          |GPIO_PIN_6|GPIO_PIN_7|GPIO_PIN_8|GPIO_PIN_9
                          |GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOH, &GPIO_InitStruct);

  /*Configure GPIO pins : LED0_Pin LED1_Pin DAC_ADDR_Pin DAC_CLR_Pin
                           DAC_LDAC_Pin */
  GPIO_InitStruct.Pin = LED0_Pin|LED1_Pin|DAC_ADDR_Pin|DAC_CLR_Pin
                          |DAC_LDAC_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PB2 PB11 PB13 PB14
                           PB15 PB8 PB9 */
  GPIO_InitStruct.Pin = GPIO_PIN_2|GPIO_PIN_11|GPIO_PIN_13|GPIO_PIN_14
                          |GPIO_PIN_15|GPIO_PIN_8|GPIO_PIN_9;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);

  /*Configure GPIO pins : PG0 PG1 PG2 PG3
                           PG4 PG5 PG6 PG7
                           PG8 PG9 PG10 PG14
                           PG15 */
  GPIO_InitStruct.Pin = GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3
                          |GPIO_PIN_4|GPIO_PIN_5|GPIO_PIN_6|GPIO_PIN_7
                          |GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_14
                          |GPIO_PIN_15;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOG, &GPIO_InitStruct);

  /*Configure GPIO pins : CHIP2_Pin CHIP1_Pin */
  GPIO_InitStruct.Pin = CHIP2_Pin|CHIP1_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOH, &GPIO_InitStruct);

  /*Configure GPIO pins : PD8 PD9 PD10 PD11
                           PD12 PD13 PD14 PD15
                           PD0 PD1 PD2 PD3
                           PD4 PD7 */
  GPIO_InitStruct.Pin = GPIO_PIN_8|GPIO_PIN_9|GPIO_PIN_10|GPIO_PIN_11
                          |GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_14|GPIO_PIN_15
                          |GPIO_PIN_0|GPIO_PIN_1|GPIO_PIN_2|GPIO_PIN_3
                          |GPIO_PIN_4|GPIO_PIN_7;
  GPIO_InitStruct.Mode = GPIO_MODE_ANALOG;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);

  /*Configure GPIO pins : SPI2_SYNC_Pin SPI1_SYNC_Pin */
  GPIO_InitStruct.Pin = SPI2_SYNC_Pin|SPI1_SYNC_Pin;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOG, &GPIO_InitStruct);

  /*AnalogSwitch Config */
  HAL_SYSCFG_AnalogSwitchConfig(SYSCFG_SWITCH_PA0, SYSCFG_SWITCH_PA0_CLOSE);

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
