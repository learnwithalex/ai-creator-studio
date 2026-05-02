import { FastifyInstance } from "fastify";
import Stripe from "stripe";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY ?? "sk_test_dev");

export async function billingRoutes(app: FastifyInstance) {
  app.post("/billing/stripe/webhook", async (req, reply) => {
    const sig = req.headers["stripe-signature"];
    if (!sig || typeof sig !== "string") return reply.code(400).send({ error: "MISSING_SIGNATURE" });
    try {
      stripe.webhooks.constructEvent(
        JSON.stringify(req.body),
        sig,
        process.env.STRIPE_WEBHOOK_SECRET ?? "whsec_dev"
      );
      return reply.send({ ok: true });
    } catch {
      return reply.code(400).send({ error: "INVALID_SIGNATURE" });
    }
  });
}
