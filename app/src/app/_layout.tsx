import { Stack } from "expo-router";

import { colors } from "@/theme";

export default function RootLayout() {
  return (
    <Stack
      screenOptions={{
        // Titles live in the content as large headings; the bar only carries navigation.
        headerTitle: "",
        headerShadowVisible: false,
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        contentStyle: { backgroundColor: colors.background },
      }}
    />
  );
}
