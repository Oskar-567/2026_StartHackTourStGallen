/**
 * Design tokens, modelled on the look of the Viseca one app: light grey surfaces,
 * large left-aligned titles, a navy hero card, black pill buttons and blue links.
 * Style only -- no Viseca logos or brand assets.
 */
export const colors = {
  background: "#FAFAFC",
  surface: "#F2F2F7",
  surfaceRaised: "#FFFFFF",
  hero: "#0B2350",
  onHero: "#FFFFFF",
  onHeroMuted: "#B8C4DA",
  text: "#111111",
  textMuted: "#5F6368",
  border: "#D9D9DF",
  primary: "#1C1C1E",
  onPrimary: "#FFFFFF",
  link: "#007AFF",
  success: "#1B7F3B",
  successSurface: "#E3F4E8",
  danger: "#C4152A",
  dangerSurface: "#FDE4E7",
  attention: "#F5A623",
  attentionSurface: "#FFF4DE",
  onAttentionSurface: "#7A4A00",
  scrim: "rgba(0, 0, 0, 0.4)",
  // The payment card on the home screen: deep navy face, soft highlight, chip gold.
  cardFace: "#0B2350",
  cardFaceHighlight: "#1D3F7A",
  cardChip: "#D9B45A",
  // Quick actions and list icons sit in pale circles.
  iconCircle: "#E9EDF5",
  onIconCircle: "#0B2350",
  // Bottom tab bar.
  tabBar: "#FFFFFF",
  tabActive: "#0B2350",
  tabInactive: "#8E8E93",
  badge: "#C4152A",
  onBadge: "#FFFFFF",
} as const;

export const radius = { card: 16, pill: 999, chip: 12, sheet: 24, paymentCard: 20 } as const;

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 } as const;

export const type = {
  largeTitle: { fontSize: 30, fontWeight: "500", color: colors.text },
  sectionTitle: { fontSize: 20, fontWeight: "500", color: colors.text },
  amountLarge: { fontSize: 34, fontWeight: "600", color: colors.text },
  amount: { fontSize: 22, fontWeight: "600", color: colors.text },
  body: { fontSize: 16, color: colors.text },
  secondary: { fontSize: 14, color: colors.textMuted },
  small: { fontSize: 13, color: colors.textMuted },
} as const;

/** Swiss formatting: `CHF 1'234.50`. */
export function formatChf(value: number | string): string {
  const number = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(number)) return `CHF ${value}`;
  const [whole, cents] = Math.abs(number).toFixed(2).split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  return `${number < 0 ? "-" : ""}CHF ${grouped}.${cents}`;
}
