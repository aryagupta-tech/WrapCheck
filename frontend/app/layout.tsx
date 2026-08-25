import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "WrapCheck · Every take accounted for",
  description: "Reconcile camera, sound, script and checksum records before source cards are erased.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
