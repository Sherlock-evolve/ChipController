/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file    thermal_control.h
  * @brief   Safe current/temperature control loop for the chip controller board.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef THERMAL_CONTROL_H
#define THERMAL_CONTROL_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stdint.h>

typedef enum
{
  THERMAL_CONTROL_OK = 0,
  THERMAL_CONTROL_ERROR,
  THERMAL_CONTROL_INVALID_PARAM,
  THERMAL_CONTROL_MEASURE_ERROR,
  THERMAL_CONTROL_TEMP_ERROR,
  THERMAL_CONTROL_OUTPUT_ERROR,
  THERMAL_CONTROL_OVERCURRENT,
  THERMAL_CONTROL_OVERVOLTAGE,
  THERMAL_CONTROL_OVERPOWER,
  THERMAL_CONTROL_OVERTEMP,
  THERMAL_CONTROL_LIMIT_CLAMPED
} ThermalControl_Status;

typedef enum
{
  THERMAL_CONTROL_MODE_OFF = 0,
  THERMAL_CONTROL_MODE_CURRENT,
  THERMAL_CONTROL_MODE_TEMPERATURE
} ThermalControl_Mode;

typedef struct
{
  ThermalControl_Mode mode;
  ThermalControl_Status status;
  uint8_t enabled;
  uint8_t faulted;
  float target_temperature_c;
  float measured_temperature_c;
  float temperature_error_c;
  float temperature_integral_a;
  float target_current_a;
  float measured_current_a;
  float load_voltage_v;
  float power_w;
  float resistance_ohm;
  float drive_voltage_v;
} ThermalControl_Snapshot;

ThermalControl_Status ThermalControl_Init(void);
ThermalControl_Status ThermalControl_Stop(void);
ThermalControl_Status ThermalControl_SetTargetCurrent(float current_a);
ThermalControl_Status ThermalControl_SetTargetTemperature(float temperature_c);
ThermalControl_Status ThermalControl_Service(uint32_t now_ms);
void ThermalControl_GetSnapshot(ThermalControl_Snapshot *snapshot);
const char *ThermalControl_StatusText(ThermalControl_Status status);
const char *ThermalControl_ModeText(ThermalControl_Mode mode);

#ifdef __cplusplus
}
#endif

#endif /* THERMAL_CONTROL_H */
