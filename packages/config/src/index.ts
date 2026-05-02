export const env = {
  gatewayPort: Number(process.env.GATEWAY_PORT ?? 4000),
  signalingPort: Number(process.env.SIGNALING_PORT ?? 4001)
};
