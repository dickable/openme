import unittest

from csme.fake_devices.fake_me import FakeME, Request, State


def start_echo(model: FakeME) -> None:
    assert model.handle(Request("RESET")).status == "ok"
    assert model.handle(Request("START")).status == "ok"
    assert model.handle(Request("ENUMERATE")).status == "ok"
    assert model.handle(Request("CONNECT", client="openme.echo")).status == "ok"


class FakeMETests(unittest.TestCase):
    def test_deterministic_startup_and_echo(self):
        first = FakeME()
        second = FakeME()
        for model in (first, second):
            start_echo(model)
            self.assertEqual(model.handle(Request("DATA", client="openme.echo", payload=b"hello")).payload, b"hello")
        self.assertEqual(first.trace, second.trace)

    def test_unknown_client_is_rejected(self):
        model = FakeME()
        start_echo(model)
        model.handle(Request("DISCONNECT", client="openme.echo"))
        response = model.handle(Request("CONNECT", client="not-a-client"))
        self.assertEqual(response.status, "unsupported-client")

    def test_message_limit_is_enforced(self):
        model = FakeME(maximum_message=4)
        start_echo(model)
        response = model.handle(Request("DATA", client="openme.echo", payload=b"12345"))
        self.assertEqual(response.status, "message-too-large")

    def test_reset_clears_session(self):
        model = FakeME()
        start_echo(model)
        self.assertEqual(model.connected_client, "openme.echo")
        model.handle(Request("RESET"))
        self.assertEqual(model.state, State.READY)
        self.assertEqual(model.connected_client, "")

    def test_unsupported_version_does_not_start(self):
        model = FakeME()
        model.handle(Request("RESET"))
        response = model.handle(Request("START", version=99))
        self.assertEqual(response.status, "unsupported-version")
        self.assertEqual(model.state, State.READY)


if __name__ == "__main__":
    unittest.main()

