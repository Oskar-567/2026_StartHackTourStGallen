/**
 * Shared building blocks in the app's visual language (see `src/theme.ts`).
 * Plain React Native only, so everything runs in Expo Go and on web.
 */
import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import { colors, radius, spacing, type } from "@/theme";

export function Screen({ children }: { children: ReactNode }) {
  return (
    <ScrollView style={styles.screen} contentContainerStyle={styles.screenContent}>
      {children}
    </ScrollView>
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

/** The dark navy summary card at the top of a screen. */
export function HeroCard({ children }: { children: ReactNode }) {
  return <View style={styles.hero}>{children}</View>;
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

/** A grey row with a chevron, like the app's navigation tiles. */
export function NavTile({ label, detail, onPress }: { label: string; detail?: string; onPress: () => void }) {
  return (
    <Pressable
      accessibilityRole="link"
      style={({ pressed }) => [styles.tile, pressed && styles.pressed]}
      onPress={onPress}
    >
      <View style={styles.tileText}>
        <Text style={type.body}>{label}</Text>
        {detail && <Text style={type.small}>{detail}</Text>}
      </View>
      <Text style={styles.chevron}>›</Text>
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
  hero: {
    backgroundColor: colors.hero,
    borderRadius: radius.card,
    padding: spacing.xl,
    gap: spacing.xs,
  },
  pill: {
    minHeight: 48,
    borderRadius: radius.pill,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
    justifyContent: "center",
  },
  pillText: { color: colors.onPrimary, fontSize: 16, fontWeight: "600" },
  pillTextSecondary: { color: colors.text },
  inactive: { opacity: 0.35 },
  pressed: { opacity: 0.75 },
  tile: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: colors.surface,
    borderRadius: radius.card,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.lg,
    gap: spacing.md,
  },
  tileText: { flex: 1, gap: 2 },
  chevron: { fontSize: 24, color: colors.textMuted },
  chip: {
    fontSize: 13,
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
    fontSize: 15,
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
  sheetTitle: { fontSize: 22, fontWeight: "500", color: colors.text, textAlign: "center" },
  sheetMessage: { fontSize: 16, color: colors.text, textAlign: "center", lineHeight: 24 },
  sheetButton: { alignSelf: "stretch", marginTop: spacing.sm },
  sheetCancel: { fontSize: 16, color: colors.link, paddingVertical: spacing.sm },
});
