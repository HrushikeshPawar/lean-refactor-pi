/* Small dependency-free Lean 4 syntax highlighter. LeanHL.line(text, state) -> HTML for one line (state.block tracks
   nested block comments across lines); LeanHL.block(text) -> HTML for a whole proof. Classes are styled in style.css. */
(() => {
  const esc = v => String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const words = s => new Set(s.split(/\s+/).filter(Boolean));
  const KEYWORDS = words(`theorem lemma def example instance structure inductive class namespace section end open import variable universe noncomputable
    private protected abbrev axiom where by have show fun match with at from then else if let in do return calc deriving mutual using only
    termination_by decreasing_by suffices obtain from this macro syntax notation local scoped attribute set_option open`);
  const TACTICS = words(`intro intros exact apply refine rw rewrite simp simp_all simpa omega cases induction rcases rintro constructor use exists ext funext
    congr norm_num ring ring_nf linarith nlinarith positivity field_simp unfold dsimp split rfl trivial contradiction exfalso by_cases by_contra
    push_neg specialize generalize subst symm trans conv first try repeat all_goals any_goals focus case next assumption aesop decide simp_rw rwa
    exacts revert clear change lift gcongr bound tauto norm_cast push_cast exact_mod_cast rename_i injection nofun nomatch absurd refine' simp_arith
    ac_rfl cc grind sorry_if rotate_left rotate_right pick_goal skip done`);
  const OPS = /^(?::=|=>|<;>|<\|>|\|>|<\||\|-|->|<-|<->|>>=|::|\+\+|[→←↔↦∀∃∧∨¬≤≥≠≈≡∈∉⊆⊂⊇∪∩∅×∘▸·∑∏⊢∣∑∫∂⁻¹∞∘↑↓⊕⊗λ•∖⊔⊓⊤⊥=<>+\-*\/%^&|!∥])/u;
  const IDENT = /^[\p{L}_][\p{L}\p{N}_'.!?₀-₉]*/u;
  const wrap = (cls, text) => `<span class="tk-${cls}">${esc(text)}</span>`;

  function line(text, state = {block: 0}) {
    let out = '', i = 0, afterDecl = false;
    const n = text.length;
    while (i < n) {
      if (state.block > 0) {                       // inside /- ... -/ (nesting allowed)
        let j = i, chunk = '';
        for (; j < n; j++) {
          if (text.startsWith('/-', j)) { state.block++; chunk += '/-'; j++; }
          else if (text.startsWith('-/', j)) { state.block--; chunk += '-/'; j++; if (!state.block) { j++; break; } }
          else chunk += text[j];
        }
        out += wrap('cm', chunk); i = j; continue;
      }
      const rest = text.slice(i), ch = text[i];
      if (rest.startsWith('--')) { out += wrap('cm', rest); break; }
      if (rest.startsWith('/-')) { state.block = 1; out += wrap('cm', '/-'); i += 2; continue; }
      let m;
      if (ch === '"') {
        let j = i + 1; while (j < n && text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
        out += wrap('str', text.slice(i, j + 1)); i = j + 1; continue;
      }
      if ((m = /^\d[\d_]*(?:\.\d+)?/.exec(rest))) { out += wrap('num', m[0]); i += m[0].length; continue; }
      if (ch === '⟨' || ch === '⟩' || ch === '‹' || ch === '›') { out += wrap('br', ch); i++; continue; }
      if (ch === '@' && text[i + 1] === '[') { const j = text.indexOf(']', i); const e = j < 0 ? n : j + 1; out += wrap('attr', text.slice(i, e)); i = e; continue; }
      if (ch === '#' && (m = /^#[a-z_]+/.exec(rest))) { out += wrap('kw', m[0]); i += m[0].length; continue; }
      if ((m = IDENT.exec(rest))) {
        const w = m[0], base = w.replace(/[.!?]+$/, '');
        let cls = null;
        if (base === 'sorry' || base === 'admit') cls = 'sorry';
        else if (afterDecl) { cls = 'name'; afterDecl = false; }
        else if (KEYWORDS.has(base)) { cls = 'kw'; afterDecl = /^(theorem|lemma|def|instance|abbrev|structure|inductive|class|axiom|example)$/.test(base); }
        else if (TACTICS.has(base)) cls = 'tac';
        else if (/^[A-Z]/.test(base) && !base.includes('.') && base.length > 1 && base !== 'True') cls = 'ty';
        out += cls ? wrap(cls, w) : esc(w); i += w.length; continue;
      }
      if ((m = OPS.exec(rest))) { out += wrap('op', m[0]); i += m[0].length; continue; }
      out += esc(ch); i++;
    }
    return out;
  }
  const block = text => { const state = {block: 0}; return String(text ?? '').split('\n').map(l => line(l, state)).join('\n'); };
  window.LeanHL = {line, block};
})();
