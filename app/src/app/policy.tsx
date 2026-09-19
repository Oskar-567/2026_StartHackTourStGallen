import { Stack } from "expo-router";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  confirmMandate,
  errorMessage,
  fetchMandates,
  revokeMandate,
  tightenMandate,
  type Mandate,
  type MandateTightening,
} from "@/services/api";
import { describeRule, purchaseLimitChf, UNCERTAINTY_DESCRIPTIONS } from "@/services/policy";

type ScreenState =
  | { kind: "loading" }
  | { kind: "loaded"; mandates: Mandate[] }
  | { kind: "failed"; message: string };

type Feedback = { tone: "success" | "error"; text: string };

export default function PolicyScreen() {
  const [state, setState] = useState<ScreenState>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const load = useCallback(
    () =>
      fetchMandates().then(
        (mandates) => setState({ kind: "loaded", mandates }),
        (error: unknown) => setState({ kind: "failed", message: errorMessage(error) }),
      ),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  /** Runs one mandate action, swaps in the server's updated mandate, reports the outcome. */
  const act = async (action: () => Promise<Mandate>, success: string) => {
    setBusy(true);
    setFeedback(null);
    try {
      const updated = await action();
      setState((previous) =>
        previous.kind === "loaded"
          ? {
              ...previous,
              mandates: previous.mandates.map((m) => (m.id === updated.id ? updated : m)),
            }
          : previous,
      );
      setFeedback({ tone: "success", text: success });
    } catch (error) {
      setFeedback({ tone: "error", text: errorMessage(error) });
    } finally {
      setBusy(false);
    }
  };

  if (state.kind === "loading") {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: "Wallet policy" }} />
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (state.kind === "failed") {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: "Wallet policy" }} />
        <Text style={styles.error}>Could not load your policy: {state.message}</Text>
        <Pressable
          style={[styles.button, styles.dark]}
          onPress={() => {
            setState({ kind: "loading" });
            load();
          }}
        >
          <Text style={styles.buttonText}>Try again</Text>
        </Pressable>
      </View>
    );
  }

  if (state.mandates.length === 0) {
    return (
      <View style={styles.centered}>
        <Stack.Screen options={{ title: "Wallet policy" }} />
        <Text style={styles.muted}>No wallet policy yet.</Text>
      </View>
    );
  }

  // Most recent first (server ordering); default to the newest one.
  const mandate = state.mandates.find((m) => m.id === selectedId) ?? state.mandates[0];
  const others = state.mandates.filter((m) => m.id !== mandate.id);

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Stack.Screen options={{ title: "Wallet policy" }} />

      <View style={styles.headerRow}>
        <Text style={styles.title}>Your wallet policy</Text>
        <StatusBadge status={mandate.status} />
      </View>

      <View style={styles.section}>
        <Text style={styles.label}>In your words</Text>
        <Text style={styles.quote}>“{mandate.instruction}”</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.label}>What the wallet enforces</Text>
        {mandate.hard_rules.length === 0 ? (
          <Text style={styles.muted}>No fixed rules.</Text>
        ) : (
          mandate.hard_rules.map((rule, index) => (
            <Text key={index} style={styles.text}>
              • {describeRule(rule)}
            </Text>
          ))
        )}
        <Text style={styles.small}>
          Checked on every purchase, together with what you asked for and whether the shop and item
          match it.
        </Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.label}>When unsure</Text>
        <Text style={styles.text}>{UNCERTAINTY_DESCRIPTIONS[mandate.uncertainty_policy]}</Text>
      </View>

      {mandate.guidance.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.label}>How we read your instruction</Text>
          {mandate.guidance.map((line, index) => (
            <Text key={index} style={styles.text}>
              • {line}
            </Text>
          ))}
        </View>
      )}

      {mandate.open_questions.length > 0 && (
        <View style={[styles.section, styles.questions]}>
          <Text style={styles.label}>Open questions</Text>
          {mandate.open_questions.map((line, index) => (
            <Text key={index} style={styles.text}>
              • {line}
            </Text>
          ))}
        </View>
      )}

      {mandate.confirmed_at && (
        <Text style={styles.small}>
          Confirmed {new Date(mandate.confirmed_at).toLocaleString()}
          {mandate.confirmed_by ? ` by ${mandate.confirmed_by}` : ""}
        </Text>
      )}

      {feedback && (
        <Text style={feedback.tone === "success" ? styles.success : styles.error}>
          {feedback.text}
        </Text>
      )}

      {mandate.status === "draft" && (
        <Pressable
          style={[styles.button, styles.approve, busy && styles.disabled]}
          disabled={busy}
          onPress={() =>
            act(() => confirmMandate(mandate.id), "Policy confirmed. Your agent may now shop.")
          }
        >
          <Text style={styles.buttonText}>Confirm this policy</Text>
        </Pressable>
      )}

      {mandate.status === "active" && (
        <>
          <TightenPanel
            mandate={mandate}
            busy={busy}
            onTighten={(change, success) => act(() => tightenMandate(mandate.id, change), success)}
          />
          <RevokeButton
            busy={busy}
            onRevoke={() =>
              act(
                () => revokeMandate(mandate.id),
                "Policy revoked. Your agent can no longer spend with this card.",
              )
            }
          />
        </>
      )}

      {others.length > 0 && (
        <View style={styles.section}>
          <Text style={styles.label}>Other policies</Text>
          {others.map((other) => (
            <Pressable
              key={other.id}
              onPress={() => {
                setSelectedId(other.id);
                setFeedback(null);
              }}
            >
              <Text style={styles.link} numberOfLines={1}>
                {other.status} · {other.instruction}
              </Text>
            </Pressable>
          ))}
        </View>
      )}
    </ScrollView>
  );
}

function StatusBadge({ status }: { status: Mandate["status"] }) {
  const palette = {
    draft: { backgroundColor: "#fff1d6", color: "#7a4a00", label: "Draft – not active yet" },
    active: { backgroundColor: "#e3f4e8", color: "#1b7f3b", label: "Active" },
    revoked: { backgroundColor: "#fde4e7", color: "#b00020", label: "Revoked" },
  }[status];
  return (
    <Text style={[styles.badge, { backgroundColor: palette.backgroundColor, color: palette.color }]}>
      {palette.label}
    </Text>
  );
}

/** Tightening only: a lower spending limit, or declining instead of asking when unsure. */
function TightenPanel({
  mandate,
  busy,
  onTighten,
}: {
  mandate: Mandate;
  busy: boolean;
  onTighten: (change: MandateTightening, success: string) => void;
}) {
  const [limit, setLimit] = useState("");
  const currentLimit = purchaseLimitChf(mandate.hard_rules);
  const parsed = Number(limit.replace(",", "."));
  const limitValid = limit.trim() !== "" && Number.isFinite(parsed) && parsed > 0;

  return (
    <View style={[styles.section, styles.panel]}>
      <Text style={styles.label}>Tighten</Text>
      <Text style={styles.small}>
        You can always make the policy stricter. Loosening it needs a new policy.
      </Text>

      <Text style={styles.text}>
        New limit per purchase (CHF)
        {currentLimit !== null ? ` – currently ${currentLimit.toFixed(2)}` : ""}
      </Text>
      <View style={styles.row}>
        <TextInput
          style={styles.input}
          value={limit}
          onChangeText={setLimit}
          keyboardType="decimal-pad"
          placeholder="e.g. 150"
        />
        <Pressable
          style={[styles.button, styles.dark, (!limitValid || busy) && styles.disabled]}
          disabled={!limitValid || busy}
          onPress={() => {
            onTighten(
              {
                // Existing rules are resent unchanged; the new one is added on top.
                hard_rules: [
                  ...mandate.hard_rules,
                  {
                    field: "authorization.billing_amount_chf",
                    operator: "<=",
                    value: parsed,
                    currency: "CHF",
                    scope: "purchase",
                  },
                ],
              },
              `Limit set to CHF ${parsed.toFixed(2)} per purchase.`,
            );
            setLimit("");
          }}
        >
          <Text style={styles.buttonText}>Apply</Text>
        </Pressable>
      </View>
      {limitValid && currentLimit !== null && parsed >= currentLimit && (
        <Text style={styles.small}>
          This is not lower than your current limit, so it will not change anything.
        </Text>
      )}

      {mandate.uncertainty_policy !== "decline" && (
        <Pressable
          style={[styles.button, styles.dark, busy && styles.disabled]}
          disabled={busy}
          onPress={() =>
            onTighten(
              { uncertainty_policy: "decline" },
              "From now on, unsure purchases are declined instead.",
            )
          }
        >
          <Text style={styles.buttonText}>Decline instead of asking when unsure</Text>
        </Pressable>
      )}
    </View>
  );
}

/** Two taps, so a stray touch cannot revoke the policy. Works on web, unlike Alert. */
function RevokeButton({ busy, onRevoke }: { busy: boolean; onRevoke: () => void }) {
  const [armed, setArmed] = useState(false);
  return (
    <View style={styles.section}>
      <Pressable
        style={[styles.button, styles.decline, busy && styles.disabled]}
        disabled={busy}
        onPress={() => {
          if (armed) {
            setArmed(false);
            onRevoke();
          } else {
            setArmed(true);
          }
        }}
      >
        <Text style={styles.buttonText}>
          {armed ? "Tap again to revoke" : "Revoke this policy"}
        </Text>
      </Pressable>
      {armed && (
        <Pressable onPress={() => setArmed(false)}>
          <Text style={styles.link}>Cancel</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 16, backgroundColor: "#ffffff", flexGrow: 1 },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 12,
    padding: 24,
    backgroundColor: "#ffffff",
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
  },
  title: { fontSize: 22, fontWeight: "600", color: "#111111" },
  badge: {
    fontSize: 13,
    fontWeight: "600",
    paddingVertical: 4,
    paddingHorizontal: 10,
    borderRadius: 12,
    overflow: "hidden",
  },
  section: { gap: 6 },
  panel: { borderWidth: 1, borderColor: "#dddddd", borderRadius: 12, padding: 16 },
  questions: { backgroundColor: "#fff8e8", borderRadius: 12, padding: 12 },
  label: { fontSize: 13, fontWeight: "600", color: "#666666", textTransform: "uppercase" },
  quote: { fontSize: 16, fontStyle: "italic", color: "#111111" },
  text: { fontSize: 15, color: "#111111" },
  small: { fontSize: 13, color: "#555555" },
  muted: { fontSize: 15, color: "#666666", textAlign: "center" },
  row: { flexDirection: "row", gap: 8, alignItems: "center" },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#cccccc",
    borderRadius: 8,
    paddingVertical: 10,
    paddingHorizontal: 12,
    fontSize: 16,
    color: "#111111",
  },
  button: {
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 8,
    alignItems: "center",
  },
  dark: { backgroundColor: "#111111" },
  approve: { backgroundColor: "#1b7f3b" },
  decline: { backgroundColor: "#b00020" },
  disabled: { opacity: 0.4 },
  buttonText: { color: "#ffffff", fontSize: 16, fontWeight: "600" },
  success: { fontSize: 15, color: "#1b7f3b" },
  error: { fontSize: 15, color: "#b00020", textAlign: "center" },
  link: { fontSize: 14, color: "#208AEF", textAlign: "center", paddingVertical: 4 },
});
