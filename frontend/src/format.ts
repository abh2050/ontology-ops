export function money(value: unknown): string {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) return "—";
  const cents = BigInt(value),
    abs = cents < 0n ? -cents : cents;
  return `${cents < 0n ? "−" : ""}R$ ${(abs / 100n).toLocaleString("pt-BR")},${(abs % 100n).toString().padStart(2, "0")}`;
}
