import unittest

from csme.mei.mei_hbm import MEIHBMModel
from csme.cpu.unicorn_runtime import UNICORN_AVAILABLE
from csme.runtime.research_console import (
    HELP_TEXT,
    ResearchConsole,
    ResearchConsoleError,
)


class ResearchConsoleTests(unittest.TestCase):
    def test_help_lists_only_supported_commands(self):
        console = ResearchConsole(model=MEIHBMModel())

        self.assertEqual(console.help(), HELP_TEXT)
        self.assertEqual(
            console.help().splitlines(),
            [
                "commands:",
                "  help",
                "  state",
                "  reset",
                "  heci-status",
                "  boot",
                "  dir [path]",
                "  cat <path>",
                "  suspend",
                "  resume",
                "  send <opcode> <utf8 payload>",
                "  trace",
            ],
        )

    def test_state_and_heci_status_are_ready_and_empty(self):
        console = ResearchConsole(model=MEIHBMModel())

        self.assertEqual(
            console.state(),
            {
                "boot": {
                    "phase": "reset",
                    "platform": "openme-synthetic-skylake",
                    "version": "0.1",
                    "loaded_modules": (),
                    "services": (),
                    "memory_map": (
                        "rom",
                        "sram",
                        "dram",
                        "heci-mmio",
                        "spi-mmio",
                        "pm-mmio",
                    ),
                    "event_count": 0,
                },
                "host_state": "ready",
                "me_state": "ready",
                "ready": True,
                "interrupts": 0,
                "pending_requests": 0,
                "pending_completions": 0,
                "last_completion": None,
            },
        )
        self.assertEqual(
            console.heci_status(),
            {
                "ready": True,
                "host_ready": True,
                "me_ready": True,
                "interrupts": 0,
                "pending_requests": 0,
                "pending_completions": 0,
            },
        )

    def test_reset_returns_to_the_same_baseline(self):
        console = ResearchConsole(model=MEIHBMModel())
        before = console.state()

        result = console.reset()

        self.assertEqual(result, before)
        self.assertEqual(console.trace(), ("reset",))

    def test_execute_serializes_structured_commands_deterministically(self):
        console = ResearchConsole(model=MEIHBMModel())

        self.assertEqual(console.execute("state"), console.execute("state"))
        self.assertEqual(console.run("heci-status"), console.execute("heci-status"))
        self.assertEqual(console.execute("trace"), "[]")

    def test_command_validation_is_bounded(self):
        console = ResearchConsole(model=MEIHBMModel())

        for command in ("", "unknown", "state extra", "send nope payload"):
            with self.subTest(command=command):
                with self.assertRaises(ResearchConsoleError):
                    console.execute(command)

        with self.assertRaises(ResearchConsoleError):
            console.send(-1, "payload")
        with self.assertRaises(ResearchConsoleError):
            console.send(1, b"\xff")


@unittest.skipUnless(UNICORN_AVAILABLE, "optional Unicorn Python package is not installed")
class ResearchConsoleBridgeTests(unittest.TestCase):
    def test_send_wraps_bridge_and_echoes_utf8_payload(self):
        console = ResearchConsole()

        result = console.send(0x20, "héllo synthetic")

        self.assertEqual(
            result,
            {
                "sequence": 0,
                "opcode": 0x20,
                "status": 0,
                "payload": "héllo synthetic",
                "payload_hex": "68c3a96c6c6f2073796e746865746963",
                "events": [
                    "reset",
                    "host_submit:0:32",
                    "me_complete:0:0",
                    "interrupts_acknowledged",
                ],
            },
        )
        self.assertEqual(console.trace(), tuple(result["events"]))
        self.assertEqual(
            console.state()["last_completion"],
            {key: result[key] for key in result if key != "events"},
        )

    def test_execute_send_accepts_hex_opcode_and_quoted_payload(self):
        console = ResearchConsole()

        result = console.execute('send 0x2a "hello world"')

        self.assertIn('"opcode":42', result)
        self.assertIn('"payload":"hello world"', result)
        self.assertIn('"status":0', result)


if __name__ == "__main__":
    unittest.main()
