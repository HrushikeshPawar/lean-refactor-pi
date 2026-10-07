theorem bisimilarity_congr_choice :
    (p ~[lts (defs := defs)] q) → (choice p r) ~[lts (defs := defs)] (choice q r) := by
  intro h
  refine ⟨ChoiceBisim, ChoiceBisim.choice h, fun _ _ hr μ => ?_⟩
  rcases hr with hb | hb
  · constructor
    · intro s htr
      cases htr with
      | choiceL htr => exact (hb.follow_fst htr).imp fun _ => And.imp Tr.choiceL ChoiceBisim.bisim
      | choiceR htr => exact ⟨s, Tr.choiceR htr, ChoiceBisim.bisim (HomBisimilarity.refl _)⟩
    · intro s htr
      cases htr with
      | choiceL htr => exact (hb.follow_snd htr).imp fun _ => And.imp Tr.choiceL ChoiceBisim.bisim
      | choiceR htr => exact ⟨s, Tr.choiceR htr, ChoiceBisim.bisim (HomBisimilarity.refl _)⟩
  · exact ⟨fun s htr => (hb.follow_fst htr).imp fun _ => And.imp_right ChoiceBisim.bisim,
      fun s htr => (hb.follow_snd htr).imp fun _ => And.imp_right ChoiceBisim.bisim⟩