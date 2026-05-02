import { describe, expect, it } from "vitest";
import { canReserveCredits, finalizeWalletDebit, reserveWalletCredits } from "./credits-math";

describe("credits math", () => {
  it("allows reservation when unreserved balance is enough", () => {
    expect(canReserveCredits({ balanceCredits: 100, reservedCredits: 20 }, 80)).toBe(true);
  });

  it("blocks reservation when unreserved balance is insufficient", () => {
    expect(canReserveCredits({ balanceCredits: 100, reservedCredits: 30 }, 71)).toBe(false);
  });

  it("increments reserved credits on reservation", () => {
    expect(reserveWalletCredits({ balanceCredits: 200, reservedCredits: 10 }, 25)).toEqual({
      balanceCredits: 200,
      reservedCredits: 35
    });
  });

  it("finalizes debit and clamps negative values", () => {
    expect(finalizeWalletDebit({ balanceCredits: 50, reservedCredits: 40 }, 100, 60)).toEqual({
      balanceCredits: 0,
      reservedCredits: 0
    });
  });
});
