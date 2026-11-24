import { Composition } from "remotion";
import { ReceiptStory } from "./ReceiptStory";

export const RemotionRoot = () => (
  <Composition id="ReceiptStory" component={ReceiptStory} durationInFrames={300} fps={30} width={1280} height={720} />
);
