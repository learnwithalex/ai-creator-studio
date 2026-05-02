import { describe, expect, it } from "vitest";
import jwt from "jsonwebtoken";
import { parseSignalingMessage, validateJoinToken } from "./protocol";

describe("signaling protocol", () => {
  it("parses valid join message", () => {
    const message = parseSignalingMessage(
      JSON.stringify({
        type: "join",
        sessionId: "s1",
        role: "browser",
        token: "token"
      })
    );
    expect(message.type).toBe("join");
  });

  it("rejects malformed signaling message", () => {
    expect(() =>
      parseSignalingMessage(
        JSON.stringify({
          type: "join",
          sessionId: "s1",
          role: "browser"
        })
      )
    ).toThrow();
  });

  it("accepts matching signed token", () => {
    const secret = "dev-secret";
    const token = jwt.sign({ sessionId: "s1", role: "worker" }, secret);
    const result = validateJoinToken({ type: "join", sessionId: "s1", role: "worker", token }, secret);
    expect(result).toEqual({ sessionId: "s1", role: "worker" });
  });

  it("rejects token payload mismatch", () => {
    const secret = "dev-secret";
    const token = jwt.sign({ sessionId: "s2", role: "worker" }, secret);
    expect(() =>
      validateJoinToken({ type: "join", sessionId: "s1", role: "worker", token }, secret)
    ).toThrow("TOKEN_PAYLOAD_MISMATCH");
  });
});
