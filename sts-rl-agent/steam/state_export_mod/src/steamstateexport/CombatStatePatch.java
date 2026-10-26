package steamstateexport;

import com.evacipated.cardcrawl.modthespire.lib.SpirePatch;
import com.evacipated.cardcrawl.modthespire.lib.SpirePostfixPatch;
import com.megacrit.cardcrawl.dungeons.AbstractDungeon;
import com.megacrit.cardcrawl.random.Random;
import communicationmod.GameStateConverter;

import java.util.HashMap;

@SpirePatch(clz = GameStateConverter.class, method = "getCombatState")
public class CombatStatePatch {
    private static HashMap<String, Object> rng(Random rng) {
        HashMap<String, Object> state = new HashMap<>();
        state.put("counter", rng.counter);
        state.put("seed0", Long.toUnsignedString(rng.random.getState(0)));
        state.put("seed1", Long.toUnsignedString(rng.random.getState(1)));
        return state;
    }

    @SpirePostfixPatch
    public static HashMap<String, Object> postfix(HashMap<String, Object> result) {
        HashMap<String, Object> rngs = new HashMap<>();
        rngs.put("ai", rng(AbstractDungeon.aiRng));
        rngs.put("card_random", rng(AbstractDungeon.cardRandomRng));
        rngs.put("misc", rng(AbstractDungeon.miscRng));
        rngs.put("monster_hp", rng(AbstractDungeon.monsterHpRng));
        rngs.put("potion", rng(AbstractDungeon.potionRng));
        rngs.put("shuffle", rng(AbstractDungeon.shuffleRng));
        result.put("rngs", rngs);
        result.put("energy_per_turn", AbstractDungeon.player.energy.energyMaster);
        return result;
    }
}
