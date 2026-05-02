# WebRTC Pipeline Notes

- Browser captures webcam at 1280x720@30.
- Browser sends offer and ICE to signaling room keyed by `sessionId`.
- Worker joins same room and returns answer + processed frames.
- TURN configuration is provided by signaling during join handshake.
