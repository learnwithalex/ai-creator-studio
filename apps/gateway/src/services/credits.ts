import { prisma } from "../lib/prisma";
import { getRedis } from "../lib/redis";
import { canReserveCredits, finalizeWalletDebit, reserveWalletCredits } from "../domain/credits-math";

const DEFAULT_FREE_CREDITS = 600;
const useInMemory = !process.env.DATABASE_URL;
const memWallets = new Map<string, Wallet>();

type Wallet = { balanceCredits: number; reservedCredits: number };

async function ensureWallet(userId: string) {
  if (useInMemory) {
    const existing = memWallets.get(userId) ?? {
      balanceCredits: DEFAULT_FREE_CREDITS,
      reservedCredits: 0
    };
    memWallets.set(userId, existing);
    return { userId, ...existing };
  }
  await prisma.user.upsert({
    where: { id: userId },
    update: {},
    create: { id: userId, email: `${userId}@local.dev` }
  });
  return prisma.creditWallet.upsert({
    where: { userId },
    update: {},
    create: { userId, balanceCredits: DEFAULT_FREE_CREDITS, reservedCredits: 0 }
  });
}

export async function getWallet(userId: string): Promise<Wallet> {
  const redis = getRedis();
  const key = `wallet:${userId}`;
  if (redis) {
    await redis.connect().catch(() => undefined);
    const cached = await redis.get(key).catch(() => null);
    if (cached) return JSON.parse(cached) as Wallet;
  }
  const wallet = await ensureWallet(userId);
  const payload = { balanceCredits: wallet.balanceCredits, reservedCredits: wallet.reservedCredits };
  if (redis) await redis.set(key, JSON.stringify(payload), "EX", 30).catch(() => undefined);
  return payload;
}

export async function reserveCredits(userId: string, amount: number): Promise<boolean> {
  const wallet = await ensureWallet(userId);
  if (!canReserveCredits(wallet, amount)) return false;
  if (useInMemory) {
    const nextWallet = reserveWalletCredits(wallet, amount);
    memWallets.set(userId, nextWallet);
    return true;
  }
  const updated = await prisma.creditWallet.update({
    where: { userId },
    data: { reservedCredits: reserveWalletCredits(wallet, amount).reservedCredits }
  });
  const redis = getRedis();
  if (redis) await redis.set(`wallet:${userId}`, JSON.stringify({ balanceCredits: updated.balanceCredits, reservedCredits: updated.reservedCredits }), "EX", 30).catch(() => undefined);
  return true;
}

export async function finalizeDebit(userId: string, actualAmount: number, reservedAmount: number, referenceId?: string): Promise<void> {
  const wallet = await ensureWallet(userId);
  const nextWallet = finalizeWalletDebit(wallet, actualAmount, reservedAmount);
  if (useInMemory) {
    memWallets.set(userId, nextWallet);
    return;
  }
  const updated = await prisma.creditWallet.update({
    where: { userId },
    data: nextWallet
  });
  await prisma.creditTransaction.create({
    data: { userId, amount: -actualAmount, reason: "SESSION_DEBIT", referenceId }
  });
  const redis = getRedis();
  if (redis) await redis.set(`wallet:${userId}`, JSON.stringify({ balanceCredits: updated.balanceCredits, reservedCredits: updated.reservedCredits }), "EX", 30).catch(() => undefined);
}

export async function releaseReservedCredits(userId: string, reservedAmount: number): Promise<void> {
  const wallet = await ensureWallet(userId);
  const nextWallet = {
    balanceCredits: wallet.balanceCredits,
    reservedCredits: Math.max(0, wallet.reservedCredits - reservedAmount)
  };
  if (useInMemory) {
    memWallets.set(userId, nextWallet);
    return;
  }
  const updated = await prisma.creditWallet.update({
    where: { userId },
    data: { reservedCredits: nextWallet.reservedCredits }
  });
  const redis = getRedis();
  if (redis) await redis.set(`wallet:${userId}`, JSON.stringify({ balanceCredits: updated.balanceCredits, reservedCredits: updated.reservedCredits }), "EX", 30).catch(() => undefined);
}
