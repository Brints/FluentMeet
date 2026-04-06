import asyncio
import base64
from pathlib import Path

import websockets

from app.core.config import settings

"""
Run this script with python -m scripts.test_audio_client
"""

# Configuration - Update these if needed
ROOM_CODE = f"{settings.ROOM_CODE}"
# NOTE: Replace 'YOUR_ACCESS_TOKEN' with the JWT token from Postman
TOKEN = f"{settings.ACCESS_TOKEN}"

WS_URL = f"ws://localhost:8000/api/v1/ws/audio/{ROOM_CODE}?token={TOKEN}"
INPUT_FILE = Path("scripts/introduction.raw")
OUTPUT_FILE = Path("scripts/voiceai_output.raw")

TIMEOUT_SECONDS = 120  # Max wait for the full pipeline to respond


async def run_audio_test():
    print(f"Connecting to {WS_URL[:80]}...")
    try:
        async with websockets.connect(
            WS_URL,
            max_size=10 * 1024 * 1024,  # Allow up to 10MB messages
            ping_interval=30,
            ping_timeout=60,
        ) as websocket:
            print("Connected!")

            # Read local raw file
            try:
                audio_data = await asyncio.to_thread(INPUT_FILE.read_bytes)
                print(f"Read {len(audio_data)} bytes from {INPUT_FILE}")
            except FileNotFoundError:
                print(f"Error: Could not find {INPUT_FILE}. Make sure it exists!")
                return

            # Send as base64 text (which our backend now supports!)
            b64_data = base64.b64encode(audio_data).decode("utf-8")
            print(f"Sending {len(b64_data)} bytes of base64 data...")
            await websocket.send(b64_data)
            print(f"Sent! Waiting up to {TIMEOUT_SECONDS}s for pipeline response...")

            # Collect all received audio chunks
            received_chunks = []
            chunk_count = 0

            try:
                while True:
                    response = await asyncio.wait_for(
                        websocket.recv(), timeout=TIMEOUT_SECONDS
                    )

                    if isinstance(response, bytes):
                        chunk_count += 1
                        received_chunks.append(response)
                        print(
                            f"  Received audio chunk #{chunk_count}:"
                            f" {len(response)} bytes"
                        )
                    else:
                        print(f"  Received text message: {response[:200]}")

            except TimeoutError:
                if received_chunks:
                    print(f"\nTimeout reached. Collected {chunk_count} chunks total.")
                else:
                    print("\nTimeout reached. No audio data received from pipeline.")
                    print(
                        "Check server console for"
                        " 'Egress: SUCCESSFULLY sent'"
                        " or 'FAILED' messages."
                    )
                    return

            except websockets.exceptions.ConnectionClosed as cc:
                print(f"\nConnection closed by server: {cc}")
                if not received_chunks:
                    return

            # Save all collected chunks to file
            if received_chunks:
                all_audio = b"".join(received_chunks)
                await asyncio.to_thread(OUTPUT_FILE.write_bytes, all_audio)
                print(f"\nSUCCESS! Saved {len(all_audio)} bytes to '{OUTPUT_FILE}'")
                print(
                    "To play: ffplay -f s16le"
                    " -sample_rate 16000"
                    f" -ch_layout mono -i {OUTPUT_FILE}"
                )

    except Exception as e:
        print(f"Connection error: {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run_audio_test())
