from dataclasses import dataclass
import os


@dataclass(frozen=True)
class DeviceConfig:
    camera_url: str
    mqtt_url: str
    barrier_url: str

    @property
    def mode(self) -> str:
        # Configuration completeness is not proof that an adapter is connected.
        return "CONFIGURED" if not self.missing else "SIMULATED"

    @property
    def missing(self) -> list[str]:
        missing = []
        if not self.camera_url.strip():
            missing.append("ITS_CAMERA_URL")
        if not self.mqtt_url.strip():
            missing.append("ITS_MQTT_URL")
        if not self.barrier_url.strip():
            missing.append("ITS_BARRIER_URL")
        return missing


def load_device_config() -> DeviceConfig:
    return DeviceConfig(
        camera_url=os.getenv("ITS_CAMERA_URL", ""),
        mqtt_url=os.getenv("ITS_MQTT_URL", ""),
        barrier_url=os.getenv("ITS_BARRIER_URL", ""),
    )
