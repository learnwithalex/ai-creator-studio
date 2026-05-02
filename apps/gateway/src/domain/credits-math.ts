export type WalletSnapshot = {
  balanceCredits: number;
  reservedCredits: number;
};

export function canReserveCredits(wallet: WalletSnapshot, requestedCredits: number): boolean {
  return wallet.balanceCredits - wallet.reservedCredits >= requestedCredits;
}

export function reserveWalletCredits(wallet: WalletSnapshot, requestedCredits: number): WalletSnapshot {
  return {
    balanceCredits: wallet.balanceCredits,
    reservedCredits: wallet.reservedCredits + requestedCredits
  };
}

export function finalizeWalletDebit(
  wallet: WalletSnapshot,
  consumedCredits: number,
  reservedCredits: number
): WalletSnapshot {
  return {
    balanceCredits: Math.max(0, wallet.balanceCredits - consumedCredits),
    reservedCredits: Math.max(0, wallet.reservedCredits - reservedCredits)
  };
}
