#include "samsung_ac_ir.h"
#include "esphome/core/log.h"

#include <cstring>

namespace esphome::samsung_ac_ir {

static const char *const TAG = "samsung_ac_ir";

static const uint8_t SECTION_LEN = 7;

// Timings sent, in microseconds (nominal values of the protocol).
static const uint32_t HEADER_MARK = 690;
static const uint32_t HEADER_SPACE = 17844;
static const uint32_t SECTION_MARK = 3086;
static const uint32_t SECTION_SPACE = 8864;
static const uint32_t BIT_MARK = 586;
static const uint32_t ONE_SPACE = 1432;
static const uint32_t ZERO_SPACE = 436;
static const uint32_t SECTION_GAP = 2886;

// Timings as the 38 kHz receiver module reports them (medians of the captures): marks come out
// shorter and spaces longer than what was sent, so decoding uses its own reference values.
static const uint32_t RX_HEADER_MARK = 605;
static const uint32_t RX_HEADER_SPACE = 18170;
static const uint32_t RX_SECTION_MARK = 3050;
static const uint32_t RX_SECTION_SPACE = 9098;
static const uint32_t RX_BIT_MARK = 500;
static const uint32_t RX_ONE_SPACE = 1499;
static const uint32_t RX_ZERO_SPACE = 500;
static const uint32_t RX_SECTION_GAP = 2950;

static const uint8_t MODE_AUTO = 0;
static const uint8_t MODE_COOL = 1;
static const uint8_t MODE_DRY = 2;
static const uint8_t MODE_FAN = 3;
static const uint8_t MODE_HEAT = 4;

static const uint8_t FAN_AUTO = 0;
static const uint8_t FAN_LOW = 2;
static const uint8_t FAN_MEDIUM = 4;
static const uint8_t FAN_HIGH = 5;
static const uint8_t FAN_TURBO = 7;

static const uint8_t SWING_VERTICAL = 2;
static const uint8_t SWING_HORIZONTAL = 3;
static const uint8_t SWING_BOTH = 4;
static const uint8_t SWING_OFF = 7;

static const uint8_t POWER_ON = 0xF0;
static const uint8_t POWER_OFF = 0xC0;

static uint8_t section_checksum(const uint8_t *s) {
  uint8_t sum = __builtin_popcount(s[0]) + __builtin_popcount(s[1] & 0x0F) + __builtin_popcount(s[2] >> 4);
  for (uint8_t i = 3; i < SECTION_LEN; i++)
    sum += __builtin_popcount(s[i]);
  return sum ^ 0xFF;
}

// The checksum is split: low nibble in the upper half of byte 1, high nibble in the lower half of byte 2.
static void apply_checksum(uint8_t *s) {
  const uint8_t sum = section_checksum(s);
  s[1] = (s[1] & 0x0F) | ((sum & 0x0F) << 4);
  s[2] = (s[2] & 0xF0) | (sum >> 4);
}

static bool checksum_ok(const uint8_t *s) {
  const uint8_t sum = section_checksum(s);
  return (s[1] >> 4) == (sum & 0x0F) && (s[2] & 0x0F) == (sum >> 4);
}

void SamsungAcClimate::transmit_state() {
  const bool on = this->mode != climate::CLIMATE_MODE_OFF;
  const uint8_t power = on ? POWER_ON : POWER_OFF;

  uint8_t mode = MODE_AUTO;
  switch (this->mode) {
    case climate::CLIMATE_MODE_COOL:
      mode = MODE_COOL;
      break;
    case climate::CLIMATE_MODE_DRY:
      mode = MODE_DRY;
      break;
    case climate::CLIMATE_MODE_FAN_ONLY:
      mode = MODE_FAN;
      break;
    case climate::CLIMATE_MODE_HEAT:
      mode = MODE_HEAT;
      break;
    default:
      break;
  }

  uint8_t fan = FAN_AUTO;
  switch (this->fan_mode.value_or(climate::CLIMATE_FAN_AUTO)) {
    case climate::CLIMATE_FAN_LOW:
      fan = FAN_LOW;
      break;
    case climate::CLIMATE_FAN_MEDIUM:
      fan = FAN_MEDIUM;
      break;
    case climate::CLIMATE_FAN_HIGH:
      fan = FAN_HIGH;
      break;
    default:
      break;
  }

  uint8_t swing = SWING_OFF;
  switch (this->swing_mode) {
    case climate::CLIMATE_SWING_VERTICAL:
      swing = SWING_VERTICAL;
      break;
    case climate::CLIMATE_SWING_HORIZONTAL:
      swing = SWING_HORIZONTAL;
      break;
    case climate::CLIMATE_SWING_BOTH:
      swing = SWING_BOTH;
      break;
    default:
      break;
  }

  const auto temp = (uint8_t) roundf(clamp<float>(this->target_temperature, 16, 30));

  // In automatic mode the remote sends a fixed mode byte: the fan cannot be chosen there.
  uint8_t mode_fan = (mode << 4) | (fan << 1) | 0x01;
  if (mode == MODE_AUTO)
    mode_fan = on ? 0x81 : 0x01;

  uint8_t first[SECTION_LEN] = {0x02, 0x02, 0x00, 0x00, 0x00, 0x00, power};
  uint8_t middle[SECTION_LEN] = {0x01, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00};
  uint8_t state[SECTION_LEN] = {
      0x01, 0x02, (uint8_t) ((0x08 | swing) << 4), 0x71, (uint8_t) ((temp - 16) << 4), mode_fan, power};
  apply_checksum(first);
  apply_checksum(middle);
  apply_checksum(state);

  // Switching power needs the long, three-section frame. It is also used for the first command
  // after boot, when the real state of the appliance is not known.
  const bool extended = !this->power_known_ || on != this->power_on_;
  this->power_known_ = true;
  this->power_on_ = on;

  const uint8_t *sections[3] = {first, middle, state};
  const uint8_t order_long[3] = {0, 1, 2};
  const uint8_t order_short[2] = {0, 2};
  const uint8_t *order = extended ? order_long : order_short;
  const uint8_t count = extended ? 3 : 2;

  auto transmit = this->transmitter_->transmit();
  auto *data = transmit.get_data();
  data->set_carrier_frequency(38000);
  data->reserve(2 + count * (4 + SECTION_LEN * 16));

  data->mark(HEADER_MARK);
  data->space(HEADER_SPACE);
  for (uint8_t n = 0; n < count; n++) {
    const uint8_t *section = sections[order[n]];
    data->mark(SECTION_MARK);
    data->space(SECTION_SPACE);
    for (uint8_t i = 0; i < SECTION_LEN; i++) {
      for (uint8_t bit = 0; bit < 8; bit++) {
        data->mark(BIT_MARK);
        data->space((section[i] >> bit) & 1 ? ONE_SPACE : ZERO_SPACE);
      }
    }
    data->mark(BIT_MARK);
    if (n + 1 < count)
      data->space(SECTION_GAP);
  }
  transmit.perform();

  ESP_LOGD(TAG, "Sent %s frame: %02X %02X %02X %02X %02X %02X %02X", extended ? "power" : "state", state[0], state[1],
           state[2], state[3], state[4], state[5], state[6]);
}

bool SamsungAcClimate::on_receive(remote_base::RemoteReceiveData data) {
  if (!data.expect_item(RX_HEADER_MARK, RX_HEADER_SPACE))
    return false;

  uint8_t last[SECTION_LEN];
  uint8_t count = 0;
  while (count < 3 && data.expect_item(RX_SECTION_MARK, RX_SECTION_SPACE)) {
    uint8_t section[SECTION_LEN] = {0};
    for (uint8_t i = 0; i < SECTION_LEN; i++) {
      for (uint8_t bit = 0; bit < 8; bit++) {
        if (data.expect_item(RX_BIT_MARK, RX_ONE_SPACE)) {
          section[i] |= 1 << bit;
        } else if (!data.expect_item(RX_BIT_MARK, RX_ZERO_SPACE)) {
          return false;
        }
      }
    }
    if (!checksum_ok(section)) {
      ESP_LOGV(TAG, "Section %u failed its checksum", count);
      return false;
    }
    memcpy(last, section, SECTION_LEN);
    count++;
    if (!data.expect_mark(RX_BIT_MARK) || !data.expect_space(RX_SECTION_GAP))
      break;
  }
  if (count < 2 || last[0] != 0x01)
    return false;

  const bool on = (last[6] & 0x30) == 0x30;
  this->power_known_ = true;
  this->power_on_ = on;

  if (!on) {
    this->mode = climate::CLIMATE_MODE_OFF;
  } else {
    switch ((last[5] >> 4) & 0x07) {
      case MODE_COOL:
        this->mode = climate::CLIMATE_MODE_COOL;
        break;
      case MODE_DRY:
        this->mode = climate::CLIMATE_MODE_DRY;
        break;
      case MODE_FAN:
        this->mode = climate::CLIMATE_MODE_FAN_ONLY;
        break;
      case MODE_HEAT:
        this->mode = climate::CLIMATE_MODE_HEAT;
        break;
      default:
        this->mode = climate::CLIMATE_MODE_HEAT_COOL;
        break;
    }
  }

  this->target_temperature = (last[4] >> 4) + 16;

  switch ((last[5] >> 1) & 0x07) {
    case FAN_LOW:
      this->fan_mode = climate::CLIMATE_FAN_LOW;
      break;
    case FAN_MEDIUM:
      this->fan_mode = climate::CLIMATE_FAN_MEDIUM;
      break;
    case FAN_HIGH:
    case FAN_TURBO:
      this->fan_mode = climate::CLIMATE_FAN_HIGH;
      break;
    default:
      this->fan_mode = climate::CLIMATE_FAN_AUTO;
      break;
  }

  switch ((last[2] >> 4) & 0x07) {
    case SWING_VERTICAL:
      this->swing_mode = climate::CLIMATE_SWING_VERTICAL;
      break;
    case SWING_HORIZONTAL:
      this->swing_mode = climate::CLIMATE_SWING_HORIZONTAL;
      break;
    case SWING_BOTH:
      this->swing_mode = climate::CLIMATE_SWING_BOTH;
      break;
    default:
      this->swing_mode = climate::CLIMATE_SWING_OFF;
      break;
  }

  ESP_LOGD(TAG, "Remote set: %s, %d C", on ? "on" : "off", (last[4] >> 4) + 16);
  this->publish_state();
  return true;
}

}  // namespace esphome::samsung_ac_ir
