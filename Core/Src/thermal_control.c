/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    thermal_control.c
  * @brief   Safe current/temperature control loop for the chip controller board.
  ******************************************************************************
  */
/* USER CODE END Header */

#include "thermal_control.h"
#include "board_output.h"
#include "board_temperature.h"
#include "chip_measure.h"

#define THERMAL_CONTROL_SERVICE_PERIOD_MS       500u
#define THERMAL_CONTROL_MIN_TARGET_TEMP_C       0.0f
#define THERMAL_CONTROL_MAX_TARGET_TEMP_C       80.0f
#define THERMAL_CONTROL_MAX_BOARD_TEMP_C        85.0f
#define THERMAL_CONTROL_MAX_TARGET_CURRENT_A    0.020f
#define THERMAL_CONTROL_MAX_CURRENT_A           0.050f
#define THERMAL_CONTROL_MAX_LOAD_VOLTAGE_V      2.000f
#define THERMAL_CONTROL_MAX_POWER_W             0.100f
#define THERMAL_CONTROL_CURRENT_GAIN_V_PER_A    4.0f
#define THERMAL_CONTROL_TEMP_KP_A_PER_C         0.001f
#define THERMAL_CONTROL_TEMP_KI_A_PER_C_S       0.00005f
#define THERMAL_CONTROL_TEMP_INTEGRAL_MIN_A     0.0f
#define THERMAL_CONTROL_TEMP_INTEGRAL_MAX_A     THERMAL_CONTROL_MAX_TARGET_CURRENT_A
#define THERMAL_CONTROL_TEMP_MAX_INTEGRATION_DT 5.0f
#define THERMAL_CONTROL_DRIVE_SLEW_STEP_V       0.020f
#define THERMAL_CONTROL_MIN_RESISTANCE_CURRENT  0.000001f

static ThermalControl_Snapshot s_snapshot = {
  .mode = THERMAL_CONTROL_MODE_OFF,
  .status = THERMAL_CONTROL_OK
};

static uint32_t s_last_service_ms;

static ThermalControl_Status thermal_control_measure(float *current_a,
                                                     float *load_voltage_v,
                                                     float *power_w,
                                                     float *resistance_ohm);
static ThermalControl_Status thermal_control_read_temperature(float *temperature_c);
static ThermalControl_Status thermal_control_apply_drive(float drive_v);
static ThermalControl_Status thermal_control_zero_output(void);
static ThermalControl_Status thermal_control_fault(ThermalControl_Status status);
static float thermal_control_temperature_pi(float error_c, float dt_s);
static void thermal_control_reset_temperature_pi(void);
static float thermal_control_absf(float value);
static float thermal_control_clampf(float value, float min_value, float max_value);
static float thermal_control_slew(float current, float target, float step);
static ThermalControl_Status thermal_control_from_measure(ChipMeasure_Status status);
static ThermalControl_Status thermal_control_from_output(BoardOutput_Status status);

ThermalControl_Status ThermalControl_Init(void)
{
  ThermalControl_Status status;

  s_snapshot.mode = THERMAL_CONTROL_MODE_OFF;
  s_snapshot.status = THERMAL_CONTROL_OK;
  s_snapshot.enabled = 0u;
  s_snapshot.faulted = 0u;
  s_snapshot.target_temperature_c = 0.0f;
  s_snapshot.measured_temperature_c = 0.0f;
  s_snapshot.temperature_error_c = 0.0f;
  s_snapshot.temperature_integral_a = 0.0f;
  s_snapshot.target_current_a = 0.0f;
  s_snapshot.measured_current_a = 0.0f;
  s_snapshot.load_voltage_v = 0.0f;
  s_snapshot.power_w = 0.0f;
  s_snapshot.resistance_ohm = 0.0f;
  s_snapshot.drive_voltage_v = 0.0f;
  s_last_service_ms = 0u;

  status = thermal_control_zero_output();
  if (status != THERMAL_CONTROL_OK)
  {
    s_snapshot.status = status;
    return status;
  }

  return THERMAL_CONTROL_OK;
}

ThermalControl_Status ThermalControl_Stop(void)
{
  ThermalControl_Status status;

  status = thermal_control_zero_output();
  s_snapshot.mode = THERMAL_CONTROL_MODE_OFF;
  s_snapshot.enabled = 0u;
  s_snapshot.faulted = 0u;
  s_snapshot.target_current_a = 0.0f;
  s_snapshot.status = status;
  thermal_control_reset_temperature_pi();

  return status;
}

ThermalControl_Status ThermalControl_SetTargetCurrent(float current_a)
{
  if ((current_a < 0.0f) || (current_a > THERMAL_CONTROL_MAX_TARGET_CURRENT_A))
  {
    return THERMAL_CONTROL_INVALID_PARAM;
  }

  s_snapshot.mode = THERMAL_CONTROL_MODE_CURRENT;
  s_snapshot.enabled = 1u;
  s_snapshot.faulted = 0u;
  s_snapshot.target_current_a = current_a;
  s_snapshot.status = THERMAL_CONTROL_OK;
  s_last_service_ms = 0u;
  thermal_control_reset_temperature_pi();

  return THERMAL_CONTROL_OK;
}

ThermalControl_Status ThermalControl_SetTargetTemperature(float temperature_c)
{
  if ((temperature_c < THERMAL_CONTROL_MIN_TARGET_TEMP_C) ||
      (temperature_c > THERMAL_CONTROL_MAX_TARGET_TEMP_C))
  {
    return THERMAL_CONTROL_INVALID_PARAM;
  }

  if (BoardTemperature_IsPresent() == 0u)
  {
    return THERMAL_CONTROL_TEMP_NOT_PRESENT;
  }

  s_snapshot.mode = THERMAL_CONTROL_MODE_TEMPERATURE;
  s_snapshot.enabled = 1u;
  s_snapshot.faulted = 0u;
  s_snapshot.target_temperature_c = temperature_c;
  s_snapshot.status = THERMAL_CONTROL_OK;
  s_last_service_ms = 0u;
  thermal_control_reset_temperature_pi();

  return THERMAL_CONTROL_OK;
}

ThermalControl_Status ThermalControl_Service(uint32_t now_ms)
{
  float current_a = 0.0f;
  float load_voltage_v = 0.0f;
  float power_w = 0.0f;
  float resistance_ohm = 0.0f;
  float measured_temperature_c = s_snapshot.measured_temperature_c;
  float target_current_a;
  float current_error_a;
  float target_drive_v;
  uint32_t elapsed_ms = THERMAL_CONTROL_SERVICE_PERIOD_MS;
  float dt_s;
  ThermalControl_Status status;

  if ((s_snapshot.enabled == 0u) || (s_snapshot.faulted != 0u))
  {
    return s_snapshot.status;
  }

  if (s_last_service_ms != 0u)
  {
    elapsed_ms = (uint32_t)(now_ms - s_last_service_ms);
    if (elapsed_ms < THERMAL_CONTROL_SERVICE_PERIOD_MS)
    {
      return s_snapshot.status;
    }
  }
  s_last_service_ms = now_ms;
  dt_s = (float)elapsed_ms / 1000.0f;

  if (s_snapshot.mode == THERMAL_CONTROL_MODE_TEMPERATURE)
  {
    status = thermal_control_read_temperature(&measured_temperature_c);
    if (status != THERMAL_CONTROL_OK)
    {
      return thermal_control_fault(status);
    }
  }

  status = thermal_control_measure(&current_a, &load_voltage_v, &power_w, &resistance_ohm);
  if (status != THERMAL_CONTROL_OK)
  {
    return thermal_control_fault(status);
  }

  s_snapshot.measured_temperature_c = measured_temperature_c;
  s_snapshot.measured_current_a = current_a;
  s_snapshot.load_voltage_v = load_voltage_v;
  s_snapshot.power_w = power_w;
  s_snapshot.resistance_ohm = resistance_ohm;

  if ((s_snapshot.mode == THERMAL_CONTROL_MODE_TEMPERATURE) &&
      (measured_temperature_c > THERMAL_CONTROL_MAX_BOARD_TEMP_C))
  {
    return thermal_control_fault(THERMAL_CONTROL_OVERTEMP);
  }

  if (current_a > THERMAL_CONTROL_MAX_CURRENT_A)
  {
    return thermal_control_fault(THERMAL_CONTROL_OVERCURRENT);
  }

  if (load_voltage_v > THERMAL_CONTROL_MAX_LOAD_VOLTAGE_V)
  {
    return thermal_control_fault(THERMAL_CONTROL_OVERVOLTAGE);
  }

  if (power_w > THERMAL_CONTROL_MAX_POWER_W)
  {
    return thermal_control_fault(THERMAL_CONTROL_OVERPOWER);
  }

  if (s_snapshot.mode == THERMAL_CONTROL_MODE_TEMPERATURE)
  {
    float temperature_error_c = s_snapshot.target_temperature_c - measured_temperature_c;

    s_snapshot.temperature_error_c = temperature_error_c;
    target_current_a = thermal_control_temperature_pi(temperature_error_c, dt_s);
    s_snapshot.target_current_a = target_current_a;
  }
  else if (s_snapshot.mode == THERMAL_CONTROL_MODE_CURRENT)
  {
    target_current_a = s_snapshot.target_current_a;
  }
  else
  {
    target_current_a = 0.0f;
  }

  current_error_a = target_current_a - current_a;
  target_drive_v = s_snapshot.drive_voltage_v + (current_error_a * THERMAL_CONTROL_CURRENT_GAIN_V_PER_A);
  target_drive_v = thermal_control_clampf(target_drive_v, 0.0f, BoardOutput_GetMaxDriveVoltage());
  target_drive_v = thermal_control_slew(s_snapshot.drive_voltage_v,
                                        target_drive_v,
                                        THERMAL_CONTROL_DRIVE_SLEW_STEP_V);

  status = thermal_control_apply_drive(target_drive_v);
  if (status != THERMAL_CONTROL_OK)
  {
    return thermal_control_fault(status);
  }

  s_snapshot.status = THERMAL_CONTROL_OK;
  return THERMAL_CONTROL_OK;
}

void ThermalControl_GetSnapshot(ThermalControl_Snapshot *snapshot)
{
  if (snapshot != NULL)
  {
    *snapshot = s_snapshot;
  }
}

const char *ThermalControl_StatusText(ThermalControl_Status status)
{
  switch (status)
  {
    case THERMAL_CONTROL_OK:
      return "OK";
    case THERMAL_CONTROL_ERROR:
      return "ERROR";
    case THERMAL_CONTROL_INVALID_PARAM:
      return "INVALID_PARAM";
    case THERMAL_CONTROL_MEASURE_ERROR:
      return "MEASURE_ERROR";
    case THERMAL_CONTROL_TEMP_ERROR:
      return "TEMP_ERROR";
    case THERMAL_CONTROL_TEMP_NOT_PRESENT:
      return "TEMP_NOT_PRESENT";
    case THERMAL_CONTROL_OUTPUT_ERROR:
      return "OUTPUT_ERROR";
    case THERMAL_CONTROL_OVERCURRENT:
      return "OVERCURRENT";
    case THERMAL_CONTROL_OVERVOLTAGE:
      return "OVERVOLTAGE";
    case THERMAL_CONTROL_OVERPOWER:
      return "OVERPOWER";
    case THERMAL_CONTROL_OVERTEMP:
      return "OVERTEMP";
    case THERMAL_CONTROL_LIMIT_CLAMPED:
      return "LIMIT_CLAMPED";
    default:
      return "UNKNOWN";
  }
}

const char *ThermalControl_ModeText(ThermalControl_Mode mode)
{
  switch (mode)
  {
    case THERMAL_CONTROL_MODE_OFF:
      return "OFF";
    case THERMAL_CONTROL_MODE_CURRENT:
      return "CURRENT";
    case THERMAL_CONTROL_MODE_TEMPERATURE:
      return "TEMPERATURE";
    default:
      return "UNKNOWN";
  }
}

static ThermalControl_Status thermal_control_measure(float *current_a,
                                                     float *load_voltage_v,
                                                     float *power_w,
                                                     float *resistance_ohm)
{
  ChipMeasure_Status measure_status;
  float signed_current_a = 0.0f;
  float current_sense_v = 0.0f;
  float signed_load_voltage_v = 0.0f;
  float raw_load_voltage_v = 0.0f;

  measure_status = ChipMeasure_SelectPath(CHIP_MEASURE_PATH_EXTERNAL);
  if (measure_status != CHIP_MEASURE_OK)
  {
    return thermal_control_from_measure(measure_status);
  }

  measure_status = ChipMeasure_ReadCurrent(&signed_current_a, &current_sense_v);
  if (measure_status != CHIP_MEASURE_OK)
  {
    return thermal_control_from_measure(measure_status);
  }

  measure_status = ChipMeasure_ReadLoadVoltage(CHIP_MEASURE_PATH_EXTERNAL,
                                               &signed_load_voltage_v,
                                               &raw_load_voltage_v);
  if (measure_status != CHIP_MEASURE_OK)
  {
    return thermal_control_from_measure(measure_status);
  }

  (void)current_sense_v;
  (void)raw_load_voltage_v;

  *current_a = thermal_control_absf(signed_current_a);
  *load_voltage_v = thermal_control_absf(signed_load_voltage_v);
  *power_w = (*current_a) * (*load_voltage_v);

  if (*current_a > THERMAL_CONTROL_MIN_RESISTANCE_CURRENT)
  {
    *resistance_ohm = (*load_voltage_v) / (*current_a);
  }
  else
  {
    *resistance_ohm = 0.0f;
  }

  return THERMAL_CONTROL_OK;
}

static ThermalControl_Status thermal_control_read_temperature(float *temperature_c)
{
  BoardTemperature_Sample sample;
  BoardTemperature_Status status;

  status = BoardTemperature_Read(&sample);
  if (status == BOARD_TEMPERATURE_OK)
  {
    *temperature_c = sample.temperature_c;
    return THERMAL_CONTROL_OK;
  }

  if (status == BOARD_TEMPERATURE_NOT_PRESENT)
  {
    return THERMAL_CONTROL_TEMP_NOT_PRESENT;
  }

  return THERMAL_CONTROL_TEMP_ERROR;
}

static ThermalControl_Status thermal_control_apply_drive(float drive_v)
{
  BoardOutput_Status output_status;

  drive_v = thermal_control_clampf(drive_v, 0.0f, BoardOutput_GetMaxDriveVoltage());
  output_status = BoardOutput_SetDriveVoltage(drive_v);
  if ((output_status != BOARD_OUTPUT_OK) && (output_status != BOARD_OUTPUT_LIMIT_CLAMPED))
  {
    return thermal_control_from_output(output_status);
  }

  s_snapshot.drive_voltage_v = drive_v;

  if (output_status == BOARD_OUTPUT_LIMIT_CLAMPED)
  {
    return THERMAL_CONTROL_LIMIT_CLAMPED;
  }

  return THERMAL_CONTROL_OK;
}

static ThermalControl_Status thermal_control_fault(ThermalControl_Status status)
{
  (void)thermal_control_zero_output();
  s_snapshot.enabled = 0u;
  s_snapshot.faulted = 1u;
  s_snapshot.target_current_a = 0.0f;
  s_snapshot.status = status;
  thermal_control_reset_temperature_pi();
  return status;
}

static float thermal_control_temperature_pi(float error_c, float dt_s)
{
  float proportional_a = error_c * THERMAL_CONTROL_TEMP_KP_A_PER_C;
  float integral_a = s_snapshot.temperature_integral_a;
  float raw_target_a = proportional_a + integral_a;

  dt_s = thermal_control_clampf(dt_s, 0.0f, THERMAL_CONTROL_TEMP_MAX_INTEGRATION_DT);

  if (!((raw_target_a >= THERMAL_CONTROL_MAX_TARGET_CURRENT_A) && (error_c > 0.0f)))
  {
    integral_a += error_c * THERMAL_CONTROL_TEMP_KI_A_PER_C_S * dt_s;
    integral_a = thermal_control_clampf(integral_a,
                                        THERMAL_CONTROL_TEMP_INTEGRAL_MIN_A,
                                        THERMAL_CONTROL_TEMP_INTEGRAL_MAX_A);
    s_snapshot.temperature_integral_a = integral_a;
  }

  raw_target_a = proportional_a + s_snapshot.temperature_integral_a;

  return thermal_control_clampf(raw_target_a, 0.0f, THERMAL_CONTROL_MAX_TARGET_CURRENT_A);
}

static void thermal_control_reset_temperature_pi(void)
{
  s_snapshot.temperature_error_c = 0.0f;
  s_snapshot.temperature_integral_a = 0.0f;
}

static ThermalControl_Status thermal_control_zero_output(void)
{
  BoardOutput_Status output_status;

  output_status = BoardOutput_SetZero();
  s_snapshot.drive_voltage_v = 0.0f;

  return thermal_control_from_output(output_status);
}

static float thermal_control_absf(float value)
{
  return (value < 0.0f) ? -value : value;
}

static float thermal_control_clampf(float value, float min_value, float max_value)
{
  if (value < min_value)
  {
    return min_value;
  }

  if (value > max_value)
  {
    return max_value;
  }

  return value;
}

static float thermal_control_slew(float current, float target, float step)
{
  if (target > (current + step))
  {
    return current + step;
  }

  if (target < (current - step))
  {
    return current - step;
  }

  return target;
}

static ThermalControl_Status thermal_control_from_measure(ChipMeasure_Status status)
{
  switch (status)
  {
    case CHIP_MEASURE_OK:
      return THERMAL_CONTROL_OK;
    case CHIP_MEASURE_INVALID_PARAM:
      return THERMAL_CONTROL_INVALID_PARAM;
    case CHIP_MEASURE_ERROR:
    case CHIP_MEASURE_TIMEOUT:
    case CHIP_MEASURE_BAD_ID:
    case CHIP_MEASURE_NO_CURRENT:
    default:
      return THERMAL_CONTROL_MEASURE_ERROR;
  }
}

static ThermalControl_Status thermal_control_from_output(BoardOutput_Status status)
{
  switch (status)
  {
    case BOARD_OUTPUT_OK:
      return THERMAL_CONTROL_OK;
    case BOARD_OUTPUT_LIMIT_CLAMPED:
      return THERMAL_CONTROL_LIMIT_CLAMPED;
    case BOARD_OUTPUT_INVALID_PARAM:
      return THERMAL_CONTROL_INVALID_PARAM;
    case BOARD_OUTPUT_OVERCURRENT:
      return THERMAL_CONTROL_OVERCURRENT;
    case BOARD_OUTPUT_ERROR:
    case BOARD_OUTPUT_TIMEOUT:
    case BOARD_OUTPUT_NO_CURRENT:
    case BOARD_OUTPUT_R42_OUT_OF_RANGE:
    default:
      return THERMAL_CONTROL_OUTPUT_ERROR;
  }
}
