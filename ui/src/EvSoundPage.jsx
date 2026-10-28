import "./ev-sound.css";
import { useOpenEmsSeo } from "./useOpenEmsSeo";

const PLAYER_SRC = "/ev-sound/player.html";

export default function EvSoundPage({ t, locale }) {
  useOpenEmsSeo(t("evSoundPageTitle"), locale, t, {
    variant: "landing",
    canonicalPath: "/ev-sound",
  });

  return (
    <div className="ev-sound-page">
      <iframe
        className="ev-sound-page__frame"
        title={t("evSoundNavLabel")}
        src={PLAYER_SRC}
      />
    </div>
  );
}
