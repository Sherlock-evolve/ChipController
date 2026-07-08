/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    board_output.c
  * @brief   Safe board output control and R42 self-test loop.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "board_output.h"
#include "main.h"

#define BOARD_OUTPUT_I2C_TIMEOUT_MS          100u
#define BOARD_OUTPUT_DAC_FULL_SCALE_V        5.0f
#define BOARD_OUTPUT_MAX_DRIVE_V             1.00f
#define BOARD_OUTPUT_R42_TEST_TARGET_A       0.005f
#define BOARD_OUTPUT_R42_TEST_MAX_A          0.050f
#define BOARD_OUTPUT_R42_TEST_MIN_A          0.0005f
#define BOARD_OUTPUT_R42_TEST_STEP_V         0.020f
#define BOARD_OUTPUT_R42_TEST_SETTLE_MS      20u
#define BOARD_OUTPUT_R42_EXPECTED_OHM        30.0f
#define BOARD_OUTPUT_R42_TOLERANCE_OHM       6.0f

extern I2C_HandleTypeDef hi2c1;

static AD5667_Handle s_dac = {
  .hi2c = &hi2c1,
  .address_7bit = AD5667_DEFAULT_I2C_ADDRESS_7BIT,
  .full_scale_volts = BOARD_OUTPUT_DAC_FULL_SCALE_V,
  .timeout_ms = BOARD_OUTPUT_I2C_TIMEOUT_MS
};

static BoardOutput_Status board_output_from_ad5667(AD5667_Status status);
static BoardOutput_Status board_output_from_measure(ChipMeasure_Status status);
static void board_output_safe_idle(void);
static float board_output_absf(float value);

BoardOutput_Status BoardOutput_Init(void)
{
  AD5667_Status status;

  HAL_GPIO_WritePin(DAC_ADDR_GPIO_Port, DAC_ADDR_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(DAC_LDAC_GPIO_Port, DAC_LDAC_Pin, GPIO_PIN_RESET);
  HAL_GPIO_WritePin(DAC_CLR_GPIO_Port, DAC_CLR_Pin, GPIO_PIN_SET);
  HAL_Delay(1u);

  status = AD5667_Init(&s_dac);
  if (status != AD5667_OK)
  {
    return board_output_from_ad5667(status);
  }

  return BoardOutput_SetZero();
}

BoardOutput_Status BoardOutput_SetDriveVoltage(float volts)
{
  float applied = volts;
  AD5667_Status status;

  if (applied < 0.0f)
  {
    applied = 0.0f;
  }
  else if (applied > BOARD_OUTPUT_MAX_DRIVE_V)
  {
    applied = BOARD_OUTPUT_MAX_DRIVE_V;
  }

  status = AD5667_SetBothVoltage(&s_dac, applied);
  if (status != AD5667_OK)
  {
    return board_output_from_ad5667(status);
  }

  if (applied != volts)
  {
    return BOARD_OUTPUT_LIMIT_CLAMPED;
  }

  return BOARD_OUTPUT_OK;
}

BoardOutput_Status BoardOutput_SetZero(void)
{
  HAL_GPIO_WritePin(DAC_CLR_GPIO_Port, DAC_CLR_Pin, GPIO_PIN_RESET);
  HAL_Delay(1u);
  HAL_GPIO_WritePin(DAC_CLR_GPIO_Port, DAC_CLR_Pin, GPIO_PIN_SET);
  HAL_Delay(1u);

  return board_output_from_ad5667(AD5667_ClearToZero(&s_dac));
}

BoardOutput_Status BoardOutput_RunR42SelfTest(BoardOutput_R42SelfTestResult *result)
{
  float drive_v = 0.0f;
  BoardOutput_Status output_status;
  ChipMeasure_Status measure_status;

  if (result == NULL)
  {
    return BOARD_OUTPUT_INVALID_PARAM;
  }

  result->requested_drive_v = BOARD_OUTPUT_MAX_DRIVE_V;
  result->applied_drive_v = 0.0f;
  result->current_a = 0.0f;
  result->current_sense_v = 0.0f;
  result->load_voltage_raw_v = 0.0f;
  result->load_voltage_v = 0.0f;
  result->resistance_ohm = 0.0f;
  result->passed = 0u;

  (void)BoardOutput_SetZero();

  measure_status = ChipMeasure_SelectPath(CHIP_MEASURE_PATH_INTERNAL_R42);
  if (measure_status != CHIP_MEASURE_OK)
  {
    (void)BoardOutput_SetZero();
    return board_output_from_measure(measure_status);
  }

  while (drive_v <= BOARD_OUTPUT_MAX_DRIVE_V)
  {
    output_status = BoardOutput_SetDriveVoltage(drive_v);
    if ((output_status != BOARD_OUTPUT_OK) && (output_status != BOARD_OUTPUT_LIMIT_CLAMPED))
    {
      board_output_safe_idle();
      return output_status;
    }

    HAL_Delay(BOARD_OUTPUT_R42_TEST_SETTLE_MS);

    measure_status = ChipMeasure_ReadCurrent(CHIP_MEASURE_PATH_INTERNAL_R42,
                                             &result->current_a,
                                             &result->current_sense_v);
    if (measure_status != CHIP_MEASURE_OK)
    {
      board_output_safe_idle();
      return board_output_from_measure(measure_status);
    }

    result->applied_drive_v = drive_v;

    if (board_output_absf(result->current_a) > BOARD_OUTPUT_R42_TEST_MAX_A)
    {
      board_output_safe_idle();
      return BOARD_OUTPUT_OVERCURRENT;
    }

    if (board_output_absf(result->current_a) >= BOARD_OUTPUT_R42_TEST_TARGET_A)
    {
      break;
    }

    drive_v += BOARD_OUTPUT_R42_TEST_STEP_V;
  }

  if (board_output_absf(result->current_a) < BOARD_OUTPUT_R42_TEST_MIN_A)
  {
    board_output_safe_idle();
    return BOARD_OUTPUT_NO_CURRENT;
  }

  measure_status = ChipMeasure_ReadLoadVoltage(CHIP_MEASURE_PATH_INTERNAL_R42,
                                               &result->load_voltage_v,
                                               &result->load_voltage_raw_v);
  board_output_safe_idle();

  if (measure_status != CHIP_MEASURE_OK)
  {
    return board_output_from_measure(measure_status);
  }

  result->resistance_ohm = board_output_absf(result->load_voltage_v) / board_output_absf(result->current_a);

  if ((result->resistance_ohm >= (BOARD_OUTPUT_R42_EXPECTED_OHM - BOARD_OUTPUT_R42_TOLERANCE_OHM)) &&
      (result->resistance_ohm <= (BOARD_OUTPUT_R42_EXPECTED_OHM + BOARD_OUTPUT_R42_TOLERANCE_OHM)))
  {
    result->passed = 1u;
    return BOARD_OUTPUT_OK;
  }

  return BOARD_OUTPUT_R42_OUT_OF_RANGE;
}

float BoardOutput_GetMaxDriveVoltage(void)
{
  return BOARD_OUTPUT_MAX_DRIVE_V;
}

const char *BoardOutput_StatusText(BoardOutput_Status status)
{
  switch (status)
  {
    case BOARD_OUTPUT_OK:
      return "OK";
    case BOARD_OUTPUT_ERROR:
      return "ERROR";
    case BOARD_OUTPUT_TIMEOUT:
      return "TIMEOUT";
    case BOARD_OUTPUT_INVALID_PARAM:
      return "INVALID_PARAM";
    case BOARD_OUTPUT_LIMIT_CLAMPED:
      return "LIMIT_CLAMPED";
    case BOARD_OUTPUT_OVERCURRENT:
      return "OVERCURRENT";
    case BOARD_OUTPUT_NO_CURRENT:
      return "NO_CURRENT";
    case BOARD_OUTPUT_R42_OUT_OF_RANGE:
      return "R42_OUT_OF_RANGE";
    default:
      return "UNKNOWN";
  }
}

static BoardOutput_Status board_output_from_ad5667(AD5667_Status status)
{
  switch (status)
  {
    case AD5667_OK:
      return BOARD_OUTPUT_OK;
    case AD5667_TIMEOUT:
      return BOARD_OUTPUT_TIMEOUT;
    case AD5667_INVALID_PARAM:
      return BOARD_OUTPUT_INVALID_PARAM;
    case AD5667_ERROR:
    default:
      return BOARD_OUTPUT_ERROR;
  }
}

static BoardOutput_Status board_output_from_measure(ChipMeasure_Status status)
{
  switch (status)
  {
    case CHIP_MEASURE_OK:
      return BOARD_OUTPUT_OK;
    case CHIP_MEASURE_TIMEOUT:
      return BOARD_OUTPUT_TIMEOUT;
    case CHIP_MEASURE_INVALID_PARAM:
      return BOARD_OUTPUT_INVALID_PARAM;
    case CHIP_MEASURE_NO_CURRENT:
      return BOARD_OUTPUT_NO_CURRENT;
    case CHIP_MEASURE_ERROR:
    case CHIP_MEASURE_BAD_ID:
    default:
      return BOARD_OUTPUT_ERROR;
  }
}

static void board_output_safe_idle(void)
{
  (void)BoardOutput_SetZero();
  (void)ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
}

static float board_output_absf(float value)
{
  return (value < 0.0f) ? -value : value;
}
