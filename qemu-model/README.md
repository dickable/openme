# QEMU model

QEMU can model the host platform and selected devices, but it does not faithfully emulate Intel ME. The initial objective is a fake ME device or software model that responds to controlled test messages.

Keep the model isolated, deterministic, documented, and independent of real firmware secrets. Test behavior with synthetic inputs and explicit protocol assumptions.

