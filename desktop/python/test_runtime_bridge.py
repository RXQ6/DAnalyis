import json
import subprocess
import sys
import unittest
from pathlib import Path

from runtime_bridge import ProtocolError, validate_command


class RuntimeBridgeProtocolTests(unittest.TestCase):
    def test_server_survives_invalid_json_and_rejects_unknown_type(self):
        entry = Path(__file__).with_name("runtime_bridge.py")
        process = subprocess.Popen(
            [sys.executable, str(entry)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        try:
            assert process.stdin is not None
            assert process.stdout is not None
            process.stdin.write("not-json\n")
            process.stdin.flush()
            invalid = json.loads(process.stdout.readline())
            self.assertEqual(invalid["type"], "runtime_error")
            self.assertEqual(invalid["error"]["code"], "invalid_json")

            process.stdin.write(
                json.dumps(
                    {
                        "protocol_version": 1,
                        "request_id": "req_unknown",
                        "run_id": None,
                        "thread_id": None,
                        "trace_id": None,
                        "sequence": 0,
                        "type": "unknown",
                        "payload": {},
                        "error": None,
                    }
                )
                + "\n"
            )
            process.stdin.flush()
            unknown = json.loads(process.stdout.readline())
            self.assertEqual(unknown["type"], "response")
            self.assertEqual(unknown["error"]["code"], "unknown_message_type")
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=5)
            if process.stdin is not None:
                process.stdin.close()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def test_valid_start_command(self):
        command = {
            "protocol_version": 1,
            "request_id": "req_1",
            "run_id": None,
            "thread_id": None,
            "trace_id": None,
            "sequence": 0,
            "type": "run.start",
            "payload": {"message": "hello"},
            "error": None,
        }
        self.assertIs(validate_command(command), command)

    def test_unknown_type_and_invalid_payload_fail_closed(self):
        for command in (
            {"protocol_version": 1, "request_id": "req_1", "type": "unknown", "payload": {}},
            {"protocol_version": 1, "request_id": "req_1", "type": "run.start", "payload": {"message": " "}},
        ):
            with self.assertRaises(ProtocolError):
                validate_command(command)


if __name__ == "__main__":
    unittest.main()
