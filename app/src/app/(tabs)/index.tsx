import { useRouter } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import {
  Card,
  Chip,
  Icon,
  ListRow,
  Loading,
  Notice,
  PaymentCard,
  PillButton,
  ProgressBar,
  QuickAction,
  Screen,
  ScreenHeader,
  SectionTitle,
} from "@/components/ui";
import {
  errorMessage,
  fetchMandates,
  fetchStepUps,
  resolveStepUp,
  type Mandate,
  type StepUp,
  type StepUpAnswer,
} from "@/services/api";
import { purchaseLimitChf } from "@/services/policy";
import { reasonLabel } from "@/services/reasons";
import { colors, formatChf, spacing, type } from "@/theme";

// The customer has 120 seconds per step-up; polling every 2s is plenty.
const POLL_INTERVAL_MS = 2_000;
const HUMAN_WINDOW_SECONDS = 120;

type QueueState =
  | { kind: "loading" }
  | { kind: "loaded"; stepUps: StepUp[]; pollError: string | null }
  | { kind: "failed"; message: string };

type Outcome = { merchant: string; answer: StepUpAnswer };

export default function ApprovalQueueScreen() {
  const router = useRouter();
  const [state, setState] = useState<QueueState>({ kind: "loading" });
  const [mandate, setMandate] = useState<Mandate | null>(null);
  const [busy, setBusy] = useState<{ id: number; answer: StepUpAnswer } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [lastOutcome, setLastOutcome] = useState<Outcome | null>(null);
  const now = useNow();

  const load = useCallback(
    () =>
      fetchStepUps().then(
        (stepUps) => setState({ kind: "loaded", stepUps, pollError: null }),
        (error: unknown) =>
          // Keep showing the last good queue if a later poll fails.
          setState((previous) =>
            previous.kind === "loaded"
              ? { ...previous, pollError: errorMessage(error) }
              : { kind: "failed", message: errorMessage(error) },
          ),
      ),
    [],
  );

  useEffect(() => {
    load();
    const timer = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // The policy summary is a nicety: if it fails, the queue still works.
  useEffect(() => {
    fetchMandates().then(
      (mandates) => setMandate(mandates.find((m) => m.status === "active") ?? mandates[0] ?? null),
      () => setMandate(null),
    );
  }, []);

  const answer = async (stepUp: StepUp, decision: StepUpAnswer) => {
    setBusy({ id: stepUp.id, answer: decision });
    setActionError(null);
    try {
      await resolveStepUp(stepUp.id, decision);
      setLastOutcome({ merchant: stepUp.merchant_name ?? "this shop", answer: decision });
      setState((previous) =>
        previous.kind === "loaded"
          ? { ...previous, stepUps: previous.stepUps.filter((s) => s.id !== stepUp.id) }
          : previous,
      );
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  const waiting = state.kind === "loaded" ? state.stepUps.length : 0;
  const limit = mandate ? purchaseLimitChf(mandate.hard_rules) : null;

  return (
    <Screen>
      <ScreenHeader
        eyebrow="Hello"
        title="Shopping agent"
        icon="bell"
        badge={waiting}
        onIconPress={() => router.push("/policy")}
      />

      <PaymentCard
        label="Limit per purchase"
        value={limit !== null ? formatChf(limit) : "No limit set"}
        caption="•••• AGENT"
        status={mandate && <Chip label={statusLabel(mandate.status)} tone={statusTone(mandate.status)} />}
      />

      <View style={styles.quickActions}>
        <QuickAction icon="policy" label="Rules" onPress={() => router.push("/policy")} />
        <QuickAction icon="shield" label="Tighten" onPress={() => router.push("/policy")} />
        <QuickAction
          icon="block"
          label="Block agent"
          tone="danger"
          onPress={() => router.push("/policy")}
        />
        <QuickAction icon="status" label="Status" onPress={() => router.push("/status")} />
      </View>

      {lastOutcome && (
        <Notice tone={lastOutcome.answer === "approve" ? "success" : "attention"}>
          {lastOutcome.answer === "approve" ? "Approved" : "Declined"} the purchase at{" "}
          {lastOutcome.merchant}.
        </Notice>
      )}
      {actionError && <Notice tone="danger">{actionError}</Notice>}

      <SectionTitle
        action={waiting > 0 ? <Chip label={`${waiting} waiting`} tone="attention" /> : undefined}
      >
        Confirm payments
      </SectionTitle>

      {state.kind === "loading" && <Loading />}

      {state.kind === "failed" && (
        <Card>
          <Text style={type.body}>Could not load the approval queue.</Text>
          <Text style={type.small}>{state.message}</Text>
          <PillButton
            label="Try again"
            variant="secondary"
            onPress={() => {
              setState({ kind: "loading" });
              load();
            }}
          />
        </Card>
      )}

      {state.kind === "loaded" && (
        <>
          {state.pollError && (
            <Notice tone="attention">Connection problem, retrying: {state.pollError}</Notice>
          )}
          {state.stepUps.length === 0 ? (
            <Card style={styles.listCard}>
              <ListRow
                icon="check"
                title="All caught up"
                subtitle="Your agent's purchases are checked automatically. If one needs you, it pauses here and nothing is paid until you decide."
              />
            </Card>
          ) : (
            state.stepUps.map((stepUp) => (
              <StepUpCard
                key={stepUp.id}
                stepUp={stepUp}
                now={now}
                busyAnswer={busy?.id === stepUp.id ? busy.answer : null}
                disabled={busy !== null}
                onAnswer={(decision) => answer(stepUp, decision)}
              />
            ))
          )}
        </>
      )}
    </Screen>
  );
}

function statusLabel(status: Mandate["status"]): string {
  return { draft: "Not active yet", active: "Active", revoked: "Revoked" }[status];
}

function statusTone(status: Mandate["status"]): "attention" | "success" | "danger" {
  return ({ draft: "attention", active: "success", revoked: "danger" } as const)[status];
}

function StepUpCard({
  stepUp,
  now,
  busyAnswer,
  disabled,
  onAnswer,
}: {
  stepUp: StepUp;
  now: number;
  busyAnswer: StepUpAnswer | null;
  disabled: boolean;
  onAnswer: (decision: StepUpAnswer) => void;
}) {
  const secondsLeft = stepUp.respond_by
    ? Math.max(0, Math.round((Date.parse(stepUp.respond_by) - now) / 1000))
    : 0;
  const expired = secondsLeft === 0;
  // A shop that tried to instruct the wallet is the one case where the evidence
  // is the point: show the quoted text without making the customer tap for it.
  const [showChecks, setShowChecks] = useState(() =>
    stepUp.reason_codes.includes("merchant_text_instruction"),
  );

  return (
    <Card style={styles.card}>
      <View style={styles.confirmTop}>
        <Text style={styles.confirmLabel}>Payment confirmation</Text>
        <View style={styles.timer}>
          <Icon name="timer" size={16} color={expired ? colors.danger : colors.textMuted} />
          <Text style={expired ? styles.expired : type.small}>
            {expired ? "Closed" : `${secondsLeft}s`}
          </Text>
        </View>
      </View>

      <View style={styles.confirmHero}>
        <View style={styles.merchantIcon}>
          <Icon name="bag" size={26} color={colors.onIconCircle} />
        </View>
        <Text style={styles.merchant}>{stepUp.merchant_name ?? "Unknown shop"}</Text>
        {stepUp.purchase_description && (
          <Text style={type.secondary}>{stepUp.purchase_description}</Text>
        )}
        <Text style={type.amountLarge}>{formatChf(stepUp.billing_amount_chf)}</Text>
      </View>

      <View style={styles.items}>
        {stepUp.items.map((item, index) => (
          <View key={index} style={styles.item}>
            <View style={styles.itemRow}>
              <Text style={[type.body, styles.itemName]}>
                {item.quantity} × {item.item_name}
              </Text>
              <Text style={type.body}>{formatChf(item.unit_price)}</Text>
            </View>
            {item.item_details && <Text style={type.small}>{item.item_details}</Text>}
          </View>
        ))}
      </View>

      <View style={styles.block}>
        <Text style={styles.label}>Why it paused</Text>
        <Text style={type.body}>{stepUp.customer_message}</Text>
        <View style={styles.chips}>
          {stepUp.reason_codes.map((code) => (
            <Chip key={code} label={reasonLabel(code)} tone="attention" />
          ))}
        </View>
      </View>

      {stepUp.evidence.length > 0 && (
        <View style={styles.block}>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ expanded: showChecks }}
            style={styles.toggle}
            onPress={() => setShowChecks((shown) => !shown)}
          >
            <Text style={styles.toggleText}>
              {showChecks ? "Hide what the wallet checked" : "Show what the wallet checked"}
            </Text>
          </Pressable>
          {showChecks &&
            stepUp.evidence.map((evidence, index) => (
              <Text key={index} style={styles.evidence}>
                • {evidence.note}
              </Text>
            ))}
        </View>
      )}

      <View style={styles.block}>
        <ProgressBar fraction={secondsLeft / HUMAN_WINDOW_SECONDS} />
        <Text style={expired ? styles.expired : type.small}>
          {expired
            ? "Answer window closed"
            : `${secondsLeft}s left to answer. Nothing is paid until you decide.`}
        </Text>
      </View>

      <View style={styles.actions}>
        <PillButton
          label="Decline"
          variant="secondary"
          style={styles.action}
          disabled={disabled || expired}
          busy={busyAnswer === "decline"}
          onPress={() => onAnswer("decline")}
        />
        <PillButton
          label="Approve"
          style={styles.action}
          disabled={disabled || expired}
          busy={busyAnswer === "approve"}
          onPress={() => onAnswer("approve")}
        />
      </View>
    </Card>
  );
}

/** Current time, refreshed every second, for the countdowns. */
function useNow(): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

const styles = StyleSheet.create({
  quickActions: { flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  listCard: { paddingVertical: spacing.xs },
  card: { gap: spacing.md, backgroundColor: colors.surfaceRaised, borderWidth: 1, borderColor: colors.border },
  confirmTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  confirmLabel: { fontSize: 15, fontWeight: "600", color: colors.textMuted, letterSpacing: 0.3 },
  timer: { flexDirection: "row", alignItems: "center", gap: 4 },
  confirmHero: { alignItems: "center", gap: spacing.xs, paddingVertical: spacing.sm },
  merchantIcon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.iconCircle,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.xs,
  },
  merchant: { fontSize: 20, fontWeight: "600", color: colors.text, textAlign: "center" },
  toggle: { alignSelf: "flex-start", paddingVertical: 2 },
  toggleText: { fontSize: 17, color: colors.link },
  items: {
    backgroundColor: colors.surface,
    borderRadius: 12,
    padding: spacing.md,
    gap: spacing.sm,
  },
  item: { gap: 2 },
  itemRow: { flexDirection: "row", justifyContent: "space-between", gap: spacing.sm },
  itemName: { flex: 1 },
  block: { gap: spacing.xs + 2 },
  label: { fontSize: 15, fontWeight: "600", color: colors.textMuted },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs + 2 },
  evidence: { fontSize: 16, color: colors.text, lineHeight: 23 },
  expired: { fontSize: 15, color: colors.danger },
  actions: { flexDirection: "row", gap: spacing.md },
  action: { flex: 1 },
});
