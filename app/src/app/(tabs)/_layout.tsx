import { Tabs } from "expo-router";

import { Icon } from "@/components/ui";
import { colors } from "@/theme";

/** Bottom tab bar, as in a card app: white bar, navy active tab, grey inactive ones. */
export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.tabActive,
        tabBarInactiveTintColor: colors.tabInactive,
        tabBarStyle: { backgroundColor: colors.tabBar, borderTopColor: colors.border },
        // Weight only: the bar sizes its label box for the default font size.
        tabBarLabelStyle: { fontWeight: "500" },
        sceneStyle: { backgroundColor: colors.background },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: "Home",
          tabBarIcon: ({ color, size }) => <Icon name="home" color={color} size={size} />,
        }}
      />
      <Tabs.Screen
        name="policy"
        options={{
          title: "Policy",
          tabBarIcon: ({ color, size }) => <Icon name="policy" color={color} size={size} />,
        }}
      />
    </Tabs>
  );
}
