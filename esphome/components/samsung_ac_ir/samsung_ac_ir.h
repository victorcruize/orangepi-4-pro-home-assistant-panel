#pragma once

#include "esphome/components/climate_ir/climate_ir.h"

#include <cinttypes>

namespace esphome::samsung_ac_ir {

/// Samsung split air conditioners (WindFree family) over infrared.
///
/// The remote always sends the complete state. A frame is a header followed by 7-byte sections,
/// each closed by its own checksum: two sections for a state change, three when power is switched.
/// Field layout and checksum were checked against 46 frames captured from the original remote.
class SamsungAcClimate final : public climate_ir::ClimateIR {
 public:
  SamsungAcClimate()
      : climate_ir::ClimateIR(16, 30, 1.0f, true, true,
                              {climate::CLIMATE_FAN_AUTO, climate::CLIMATE_FAN_LOW, climate::CLIMATE_FAN_MEDIUM,
                               climate::CLIMATE_FAN_HIGH},
                              {climate::CLIMATE_SWING_OFF, climate::CLIMATE_SWING_VERTICAL,
                               climate::CLIMATE_SWING_HORIZONTAL, climate::CLIMATE_SWING_BOTH}) {}

 protected:
  /// Transmit via IR the state of this climate controller.
  void transmit_state() override;
  /// Follow the original remote: decode a received frame and adopt its state.
  bool on_receive(remote_base::RemoteReceiveData data) override;

  bool power_known_{false};
  bool power_on_{false};
};

}  // namespace esphome::samsung_ac_ir
