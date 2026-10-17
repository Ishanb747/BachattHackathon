import { AiOrb } from "../atom";

// The call orb (round AtomUI orb). Kept as one component so every screen matches.
export default function RupeeOrb({ state = "idle", size = 220 }) {
  return <AiOrb state={state} size={size} />;
}
