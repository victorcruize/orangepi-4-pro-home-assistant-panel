import esphome.codegen as cg
from esphome.components import climate_ir
from esphome.types import ConfigType

AUTO_LOAD = ["climate_ir"]

samsung_ac_ir_ns = cg.esphome_ns.namespace("samsung_ac_ir")
SamsungAcClimate = samsung_ac_ir_ns.class_("SamsungAcClimate", climate_ir.ClimateIR)

CONFIG_SCHEMA = climate_ir.climate_ir_with_receiver_schema(SamsungAcClimate)


async def to_code(config: ConfigType) -> None:
    await climate_ir.new_climate_ir(config)
