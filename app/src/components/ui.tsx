/**
 * Shared building blocks in the app's visual language (see `src/theme.ts`).
 * Plain React Native plus expo-symbols, so everything runs in Expo Go and on web.
 */
import { SymbolView, type SymbolViewProps } from "expo-symbols";
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type ColorValue,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { colors, radius, spacing, type } from "@/theme";

/** Screens draw their own titles (no navigation header), so they pad for the status bar. */
export function Screen({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[styles.screenContent, { paddingTop: insets.top + spacing.lg }]}
    >
      {children}
    </ScrollView>
  );
}

/**
 * Icons: SF Symbols on iOS, Material Symbols on Android and web (both via expo-symbols).
 * Every icon needs a name per platform, or Android and web render nothing.
 */
const ICONS = {
  home: { ios: "house", android: "home", web: "home" },
  policy: { ios: "slider.horizontal.3", android: "tune", web: "tune" },
  status: { ios: "server.rack", android: "dns", web: "dns" },
  block: { ios: "hand.raised", android: "block", web: "block" },
  bell: { ios: "bell", android: "notifications", web: "notifications" },
  check: { ios: "checkmark.circle", android: "task_alt", web: "task_alt" },
  chevronRight: { ios: "chevron.right", android: "chevron_right", web: "chevron_right" },
  back: { ios: "chevron.left", android: "chevron_left", web: "chevron_left" },
  shield: { ios: "checkmark.shield", android: "verified_user", web: "verified_user" },
  bag: { ios: "bag", android: "shopping_bag", web: "shopping_bag" },
  lock: { ios: "lock", android: "lock", web: "lock" },
  contactless: { ios: "wave.3.right", android: "contactless", web: "contactless" },
  timer: { ios: "clock", android: "schedule", web: "schedule" },
  rule: { ios: "list.bullet.rectangle", android: "rule", web: "rule" },
} satisfies Record<string, Required<Exclude<SymbolViewProps["name"], string>>>;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  size = 22,
  color = colors.text,
}: {
  name: IconName;
  size?: number;
  color?: ColorValue;
}) {
  return <SymbolView name={ICONS[name]} size={size} tintColor={color} />;
}

/** Top of a tab: small greeting line, large title, and an icon button with an optional badge. */
export function ScreenHeader({
  eyebrow,
  title,
  icon,
  badge,
  onIconPress,
}: {
  eyebrow?: string;
  title: string;
  icon?: IconName;
  badge?: number;
  onIconPress?: () => void;
}) {
  return (
    <View style={styles.header}>
      <View style={styles.headerText}>
        {eyebrow && <Text style={type.secondary}>{eyebrow}</Text>}
        <Text style={type.largeTitle}>{title}</Text>
      </View>
      {icon && (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={badge ? `${title}, ${badge} waiting` : title}
          style={({ pressed }) => [styles.headerButton, pressed && styles.pressed]}
          onPress={onIconPress}
        >
          <Icon name={icon} color={colors.onIconCircle} />
          {!!badge && (
            <View style={styles.badge}>
              <Text style={styles.badgeText}>{badge > 9 ? "9+" : badge}</Text>
            </View>
          )}
        </Pressable>
      )}
    </View>
  );
}

/** "‹ Back" for screens pushed on top of the tabs. */
export function BackLink({ onPress }: { onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" style={styles.back} onPress={onPress}>
      <Icon name="back" size={20} color={colors.link} />
      <Text style={styles.backText}>Back</Text>
    </Pressable>
  );
}

/**
 * The card visual at the top of the home screen, in the style of a payment card:
 * navy face, chip, contactless mark, masked number, a label and one headline value.
 */
export function PaymentCard({
  label,
  value,
  caption,
  status,
}: {
  label: string;
  value: string;
  caption: string;
  status?: ReactNode;
}) {
  return (
    <View style={styles.paymentCard}>
      <View style={styles.paymentCardGlow} />
      <View style={styles.paymentCardTop}>
        <View style={styles.cardChip} />
        <Icon name="contactless" size={24} color={colors.onHero} />
      </View>
      <View style={styles.paymentCardBody}>
        <Text style={styles.paymentCardLabel}>{label}</Text>
        <Text style={styles.paymentCardValue}>{value}</Text>
      </View>
      <View style={styles.paymentCardBottom}>
        <Text style={styles.paymentCardCaption} numberOfLines={1}>
          {caption}
        </Text>
        {status}
      </View>
    </View>
  );
}

/** A round icon button with a label underneath, as in a row of card shortcuts. */
export function QuickAction({
  icon,
  label,
  onPress,
  tone = "default",
}: {
  icon: IconName;
  label: string;
  onPress: () => void;
  tone?: "default" | "danger";
}) {
  const color = tone === "danger" ? colors.danger : colors.onIconCircle;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      style={({ pressed }) => [styles.quickAction, pressed && styles.pressed]}
      onPress={onPress}
    >
      <View style={[styles.quickIcon, tone === "danger" && styles.quickIconDanger]}>
        <Icon name={icon} color={color} />
      </View>
      <Text style={styles.quickLabel} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

/** A list row: icon in a circle, title and subtitle, optional trailing text or chevron. */
export function ListRow({
  icon,
  title,
  subtitle,
  trailing,
  onPress,
  divider = false,
}: {
  icon: IconName;
  title: string;
  subtitle?: string;
  trailing?: string;
  onPress?: () => void;
  divider?: boolean;
}) {
  const content = (
    <>
      <View style={styles.rowIcon}>
        <Icon name={icon} size={20} color={colors.onIconCircle} />
      </View>
      <View style={styles.rowText}>
        <Text style={type.body}>{title}</Text>
        {subtitle && <Text style={type.small}>{subtitle}</Text>}
      </View>
      {trailing && <Text style={styles.rowTrailing}>{trailing}</Text>}
      {onPress && <Icon name="chevronRight" size={18} color={colors.textMuted} />}
    </>
  );
  const style = [styles.row, divider && styles.rowDivider];
  return onPress ? (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [...style, pressed && styles.pressed]}
      onPress={onPress}
    >
      {content}
    </Pressable>
  ) : (
    <View style={style}>{content}</View>
  );
}

export function LargeTitle({ children }: { children: ReactNode }) {
  return <Text style={type.largeTitle}>{children}</Text>;
}

export function SectionTitle({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={type.sectionTitle}>{children}</Text>
      {action}
    </View>
  );
}

export function Card({
  children,
  style,
}: {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
}) {
  return <View style={[styles.card, style]}>{children}</View>;
}

type ButtonVariant = "primary" | "secondary" | "danger";

export function PillButton({
  label,
  onPress,
  variant = "primary",
  disabled = false,
  busy = false,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: ButtonVariant;
  disabled?: boolean;
  busy?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const inactive = disabled || busy;
  return (
    <Pressable
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.pill,
        pillVariants[variant],
        inactive && styles.inactive,
        pressed && !inactive && styles.pressed,
        style,
      ]}
      disabled={inactive}
      onPress={onPress}
    >
      {busy ? (
        <ActivityIndicator color={variant === "secondary" ? colors.text : colors.onPrimary} />
      ) : (
        <Text style={[styles.pillText, variant === "secondary" && styles.pillTextSecondary]}>
          {label}
        </Text>
      )}
    </Pressable>
  );
}

type ChipTone = "neutral" | "attention" | "success" | "danger";

export function Chip({ label, tone = "neutral" }: { label: string; tone?: ChipTone }) {
  return <Text style={[styles.chip, chipTones[tone]]}>{label}</Text>;
}

/** Shrinking bar for a countdown, like the app's PIN timer. `fraction` is 0..1. */
export function ProgressBar({ fraction }: { fraction: number }) {
  const clamped = Math.max(0, Math.min(1, fraction));
  return (
    <View style={styles.track}>
      <View style={[styles.bar, { width: `${clamped * 100}%` }]} />
    </View>
  );
}

export function Notice({ tone, children }: { tone: "success" | "danger" | "attention"; children: ReactNode }) {
  return <Text style={[styles.notice, noticeTones[tone]]}>{children}</Text>;
}

export function Loading() {
  return <ActivityIndicator size="large" color={colors.text} style={styles.loading} />;
}

/** Bottom-sheet confirmation: icon, centred title, explanation, one decisive pill. */
export function ConfirmSheet({
  visible,
  icon,
  title,
  message,
  confirmLabel,
  onConfirm,
  onCancel,
}: {
  visible: boolean;
  icon: string;
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onCancel}>
      <Pressable style={styles.scrim} onPress={onCancel}>
        {/* Swallow taps on the sheet itself so only the scrim dismisses. */}
        <Pressable style={styles.sheet} onPress={() => {}}>
          <View style={styles.grabber} />
          <Text style={styles.sheetIcon}>{icon}</Text>
          <Text style={styles.sheetTitle}>{title}</Text>
          <Text style={styles.sheetMessage}>{message}</Text>
          <PillButton label={confirmLabel} onPress={onConfirm} style={styles.sheetButton} />
          <Pressable onPress={onCancel}>
            <Text style={styles.sheetCancel}>Cancel</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const pillVariants = StyleSheet.create({
  primary: { backgroundColor: colors.primary },
  secondary: {
    backgroundColor: colors.surfaceRaised,
    borderWidth: 1,
    borderColor: colors.border,
  },
  danger: { backgroundColor: colors.danger },
});

const chipTones = StyleSheet.create({
  neutral: { backgroundColor: colors.surfaceRaised, color: colors.text },
  attention: { backgroundColor: colors.attentionSurface, color: colors.onAttentionSurface },
  success: { backgroundColor: colors.successSurface, color: colors.success },
  danger: { backgroundColor: colors.dangerSurface, color: colors.danger },
});

const noticeTones = StyleSheet.create({
  success: { backgroundColor: colors.successSurface, color: colors.success },
  danger: { backgroundColor: colors.dangerSurface, color: colors.danger },
  attention: { backgroundColor: colors.attentionSurface, color: colors.onAttentionSurface },
});

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  screenContent: { padding: spacing.lg, paddingBottom: 48, gap: spacing.lg },
  header: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  headerText: { flex: 1, gap: 2 },
  headerButton: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.iconCircle,
    alignItems: "center",
    justifyContent: "center",
  },
  badge: {
    position: "absolute",
    top: 2,
    right: 2,
    minWidth: 18,
    height: 18,
    borderRadius: 9,
    paddingHorizontal: 4,
    backgroundColor: colors.badge,
    alignItems: "center",
    justifyContent: "center",
  },
  badgeText: { color: colors.onBadge, fontSize: 11, fontWeight: "700" },
  back: { flexDirection: "row", alignItems: "center", gap: 2, alignSelf: "flex-start" },
  backText: { fontSize: 16, color: colors.link },
  paymentCard: {
    backgroundColor: colors.cardFace,
    borderRadius: radius.paymentCard,
    padding: spacing.xl,
    aspectRatio: 1.586, // ISO/IEC 7810 ID-1, the shape of a real card
    justifyContent: "space-between",
    overflow: "hidden",
  },
  // A large soft circle in the corner gives the flat navy face some depth.
  paymentCardGlow: {
    position: "absolute",
    width: 260,
    height: 260,
    borderRadius: 130,
    right: -90,
    top: -110,
    backgroundColor: colors.cardFaceHighlight,
    opacity: 0.6,
  },
  paymentCardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  cardChip: { width: 40, height: 30, borderRadius: 6, backgroundColor: colors.cardChip },
  paymentCardBody: { gap: 2 },
  paymentCardLabel: { fontSize: 14, color: colors.onHeroMuted },
  paymentCardValue: { fontSize: 32, fontWeight: "600", color: colors.onHero },
  paymentCardBottom: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: spacing.md,
  },
  paymentCardCaption: {
    flex: 1,
    fontSize: 15,
    letterSpacing: 2,
    color: colors.onHero,
  },
  quickAction: { flex: 1, alignItems: "center", gap: spacing.xs + 2 },
  quickIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.iconCircle,
    alignItems: "center",
    justifyContent: "center",
  },
  quickIconDanger: { backgroundColor: colors.dangerSurface },
  quickLabel: { fontSize: 13, color: colors.text },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingVertical: spacing.md,
  },
  rowDivider: { borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border },
  rowIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: colors.iconCircle,
    alignItems: "center",
    justifyContent: "center",
  },
  rowText: { flex: 1, gap: 2 },
  rowTrailing: { fontSize: 16, fontWeight: "600", color: colors.text },
  sectionHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "baseline",
    marginTop: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    padding: spacing.lg,
    gap: spacing.sm,
  },
  pill: {
    minHeight: 52,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
  },
  pillText: { color: colors.onPrimary, fontSize: 18, fontWeight: "600" },
  pillTextSecondary: { color: colors.text },
  inactive: { opacity: 0.35 },
  pressed: { opacity: 0.75 },
  chip: {
    fontSize: 15,
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: radius.chip,
    overflow: "hidden",
  },
  track: {
    height: 6,
    borderRadius: 3,
    backgroundColor: colors.surfaceRaised,
    overflow: "hidden",
  },
  bar: { height: 6, borderRadius: 3, backgroundColor: colors.attention },
  notice: {
    fontSize: 17,
    padding: spacing.md,
    borderRadius: radius.chip,
    overflow: "hidden",
  },
  loading: { marginTop: 48 },
  scrim: { flex: 1, backgroundColor: colors.scrim, justifyContent: "flex-end" },
  sheet: {
    backgroundColor: colors.surfaceRaised,
    borderTopLeftRadius: radius.sheet,
    borderTopRightRadius: radius.sheet,
    padding: spacing.xl,
    paddingBottom: 40,
    alignItems: "center",
    gap: spacing.md,
  },
  grabber: { width: 40, height: 5, borderRadius: 3, backgroundColor: colors.border },
  sheetIcon: { fontSize: 40, marginTop: spacing.sm },
  sheetTitle: { fontSize: 24, fontWeight: "500", color: colors.text, textAlign: "center" },
  sheetMessage: { fontSize: 18, color: colors.text, textAlign: "center", lineHeight: 27 },
  sheetButton: { alignSelf: "stretch", marginTop: spacing.sm },
  sheetCancel: { fontSize: 18, color: colors.link, paddingVertical: spacing.sm },
});
