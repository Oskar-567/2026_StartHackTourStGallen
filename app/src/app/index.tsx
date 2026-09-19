import { Link, Stack } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import {
  errorMessage,
  fetchStepUps,
  resolveStepUp,
  type StepUp,
  type StepUpAnswer,
} from "@/services/api";
import { reasonLabel } from "@/services/reasons";

// The customer has 120 seconds per step-up; polling every 2s is plenty.
const POLL_INTERVAL_MS = 2_000;

type QueueState =
  | { kind: "loading" }
  | { kind: "loaded"; stepUps: StepUp[]; pollError: string | null }
  | { kind: "failed"; message: string };

type Outcome = { merchant: string; answer: StepUpAnswer };

export default function ApprovalQueueScreen() {
  const [state, setState] = useState<QueueState>({ kind: "loading" });
  const [busyId, setBusyId] = useState<number | null>(null);
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

  const answer = async (stepUp: StepUp, decision: StepUpAnswer) => {
    setBusyId(stepUp.id);
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
      setBusyId(null);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: "Approvals" }} />

      <Text style={styles.intro}>
        Purchases your shopping agent wants to make that the wallet could not approve on its own.
        Nothing is paid until you decide.
      </Text>

      {lastOutcome && (
        <Text style={styles.success}>
          {lastOutcome.answer === "approve" ? "Approved" : "Declined"} the purchase at{" "}
          {lastOutcome.merchant}.
        </Text>
      )}
      {actionError && <Text style={styles.error}>{actionError}</Text>}

      {state.kind === "loading" && <ActivityIndicator size="large" style={styles.spinner} />}

      {state.kind === "failed" && (
        <View style={styles.centered}>
          <Text style={styles.error}>Could not load the approval queue: {state.message}</Text>
          <Pressable
            style={styles.secondaryButton}
            onPress={() => {
              setState({ kind: "loading" });
              load();
            }}
          >
            <Text style={styles.secondaryButtonText}>Try again</Text>
          </Pressable>
        </View>
      )}

      {state.kind === "loaded" && (
        <>
          {state.pollError && (
            <Text style={styles.warning}>Connection problem, retrying: {state.pollError}</Text>
          )}
          {state.stepUps.length === 0 ? (
            <Text style={styles.muted}>Nothing is waiting for you.</Text>
          ) : (
            state.stepUps.map((stepUp) => (
              <StepUpCard
                key={stepUp.id}
                stepUp={stepUp}
                now={now}
                busy={busyId === stepUp.id}
                disabled={busyId !== null}
                onAnswer={(decision) => answer(stepUp, decision)}
              />
            ))
          )}
        </>
      )}

      <Link href="/status" style={styles.link}>
        Server status
      </Link>
    </ScrollView>
  );
}

function StepUpCard({
  stepUp,
  now,
  busy,
  disabled,
  onAnswer,
}: {
  stepUp: StepUp;
  now: number;
  busy: boolean;
  disabled: boolean;
  onAnswer: (decision: StepUpAnswer) => void;
}) {
  const secondsLeft = stepUp.respond_by
    ? Math.max(0, Math.round((Date.parse(stepUp.respond_by) - now) / 1000))
    : 0;
  const expired = secondsLeft === 0;

  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <Text style={styles.merchant}>{stepUp.merchant_name ?? "Unknown shop"}</Text>
        <Text style={styles.amount}>CHF {stepUp.billing_amount_chf}</Text>
      </View>
      {stepUp.purchase_description && (
        <Text style={styles.muted}>{stepUp.purchase_description}</Text>
      )}

      <View style={styles.section}>
        {stepUp.items.map((item, index) => (
          <View key={index} style={styles.item}>
            <Text style={styles.text}>
              {item.quantity} × {item.item_name} · CHF {item.unit_price.toFixed(2)}
            </Text>
            {item.item_details && <Text style={styles.small}>{item.item_details}</Text>}
          </View>
        ))}
      </View>

      <View style={styles.section}>
        <Text style={styles.label}>Why it paused</Text>
        <Text style={styles.text}>{stepUp.customer_message}</Text>
        <View style={styles.chips}>
          {stepUp.reason_codes.map((code) => (
            <Text key={code} style={styles.chip}>
              {reasonLabel(code)}
            </Text>
          ))}
        </View>
      </View>

      {stepUp.evidence.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.label}>What the wallet checked</Text>
          {stepUp.evidence.map((evidence, index) => (
            <Text key={index} style={styles.small}>
              • {evidence.note}
            </Text>
          ))}
        </View>
      )}

      <Text style={expired ? styles.error : styles.muted}>
        {expired ? "Answer window closed" : `${secondsLeft}s left to answer`}
      </Text>

      <View style={styles.actions}>
        <Pressable
          style={[styles.button, styles.decline, (disabled || expired) && styles.disabled]}
          disabled={disabled || expired}
          onPress={() => onAnswer("decline")}
        >
          <Text style={styles.buttonText}>Decline</Text>
        </Pressable>
        <Pressable
          style={[styles.button, styles.approve, (disabled || expired) && styles.disabled]}
          disabled={disabled || expired}
          onPress={() => onAnswer("approve")}
        >
          {busy ? (
            <ActivityIndicator color="#ffffff" />
          ) : (
            <Text style={styles.buttonText}>Approve</Text>
          )}
        </Pressable>
      </View>
    </View>
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
  container: { padding: 16, gap: 12, backgroundColor: "#ffffff", flexGrow: 1 },
  intro: { fontSize: 15, color: "#333333" },
  spinner: { marginTop: 32 },
  centered: { alignItems: "center", gap: 12, marginTop: 24 },
  card: {
    borderWidth: 1,
    borderColor: "#dddddd",
    borderRadius: 12,
    padding: 16,
    gap: 8,
    backgroundColor: "#fafafa",
  },
  cardHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  merchant: { fontSize: 18, fontWeight: "600", color: "#111111", flexShrink: 1 },
  amount: { fontSize: 18, fontWeight: "600", color: "#111111" },
  section: { gap: 4, marginTop: 4 },
  item: { gap: 2 },
  label: { fontSize: 13, fontWeight: "600", color: "#666666", textTransform: "uppercase" },
  text: { fontSize: 15, color: "#111111" },
  small: { fontSize: 13, color: "#444444" },
  muted: { fontSize: 14, color: "#666666" },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 },
  chip: {
    fontSize: 12,
    color: "#7a4a00",
    backgroundColor: "#fff1d6",
    paddingVertical: 3,
    paddingHorizontal: 8,
    borderRadius: 10,
    overflow: "hidden",
  },
  actions: { flexDirection: "row", gap: 12, marginTop: 8 },
  button: { flex: 1, paddingVertical: 12, borderRadius: 8, alignItems: "center" },
  approve: { backgroundColor: "#1b7f3b" },
  decline: { backgroundColor: "#b00020" },
  disabled: { opacity: 0.4 },
  buttonText: { color: "#ffffff", fontSize: 16, fontWeight: "600" },
  secondaryButton: {
    paddingVertical: 10,
    paddingHorizontal: 20,
    borderRadius: 8,
    backgroundColor: "#111111",
  },
  secondaryButtonText: { color: "#ffffff", fontSize: 16 },
  success: { fontSize: 15, color: "#1b7f3b" },
  warning: { fontSize: 14, color: "#7a4a00" },
  error: { fontSize: 15, color: "#b00020" },
  link: { marginTop: 16, fontSize: 14, color: "#208AEF", textAlign: "center" },
});
