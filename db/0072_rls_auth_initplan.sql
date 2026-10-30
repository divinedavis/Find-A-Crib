-- findacrib: wrap auth.*() in (select ...) so RLS evaluates it once per
-- query, not once per row (advisor auth_rls_initplan). Same predicates.
-- Generated from live pg_policies 2026-10-30.

alter policy "own_select" on public."saved_buildings"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "own_delete" on public."saved_buildings"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "visits_insert" on public."visits"
  with check (((user_id IS NULL) OR (user_id = ( SELECT auth.uid() AS uid))));

alter policy "events_insert" on public."events"
  with check (((user_id IS NULL) OR (user_id = ( SELECT auth.uid() AS uid))));

alter policy "sub_select_own" on public."subscriptions"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "cat_select_own" on public."categories"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "cat_update_own" on public."categories"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "cat_delete_own" on public."categories"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "own_update" on public."saved_buildings"
  using ((( SELECT auth.uid() AS uid) = user_id))
  with check ((( SELECT auth.uid() AS uid) = user_id));

alter policy "ss_select_own" on public."saved_searches"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "ss_delete_own" on public."saved_searches"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "own_insert" on public."saved_buildings"
  with check ((( SELECT auth.uid() AS uid) = user_id));

alter policy "casa_watches_own_read" on public."casa_watches"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "chat_keys_own" on public."chat_keys"
  using ((user_id = ( SELECT auth.uid() AS uid)))
  with check ((user_id = ( SELECT auth.uid() AS uid)));

alter policy "chat_members_join" on public."chat_members"
  with check (((user_id = ( SELECT auth.uid() AS uid)) AND (NOT chat_is_banned())));

alter policy "chat_members_leave" on public."chat_members"
  using ((user_id = ( SELECT auth.uid() AS uid)));

alter policy "chat_messages_post" on public."chat_messages"
  with check (((sender = ( SELECT auth.uid() AS uid)) AND chat_is_member(bbl) AND (NOT chat_is_banned())));

alter policy "chat_messages_delete" on public."chat_messages"
  using ((sender = ( SELECT auth.uid() AS uid)));

alter policy "comments_delete_own" on public."building_comments"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "comments_insert_own" on public."building_comments"
  with check (((( SELECT auth.uid() AS uid) = user_id) AND ((parent_id IS NULL) OR (EXISTS ( SELECT 1
   FROM building_comments p
  WHERE ((p.id = building_comments.parent_id) AND (p.parent_id IS NULL) AND (p.bbl = building_comments.bbl)))))));

alter policy "likes_insert_own" on public."comment_likes"
  with check ((( SELECT auth.uid() AS uid) = user_id));

alter policy "likes_delete_own" on public."comment_likes"
  using ((( SELECT auth.uid() AS uid) = user_id));

alter policy "reports_insert_own" on public."comment_reports"
  with check ((( SELECT auth.uid() AS uid) = reporter_id));

alter policy "reports_read_own" on public."comment_reports"
  using ((( SELECT auth.uid() AS uid) = reporter_id));

alter policy "blocks_own" on public."comment_blocks"
  using ((( SELECT auth.uid() AS uid) = user_id))
  with check ((( SELECT auth.uid() AS uid) = user_id));

alter policy "cat_insert_plus" on public."categories"
  with check (((( SELECT auth.uid() AS uid) = user_id) AND has_features(( SELECT auth.uid() AS uid))));

alter policy "ss_insert_plus" on public."saved_searches"
  with check (((( SELECT auth.uid() AS uid) = user_id) AND has_features(( SELECT auth.uid() AS uid))));

alter policy "chat_blocks_own" on public."chat_blocks"
  using ((blocker = ( SELECT auth.uid() AS uid)))
  with check ((blocker = ( SELECT auth.uid() AS uid)));

alter policy "chat_reports_file" on public."chat_reports"
  with check (((reporter = ( SELECT auth.uid() AS uid)) AND chat_is_member(bbl)));

alter policy "chat_members_read" on public."chat_members"
  using (((user_id = ( SELECT auth.uid() AS uid)) OR chat_is_member(bbl)));

alter policy "chat_devices_own" on public."chat_devices"
  using ((user_id = ( SELECT auth.uid() AS uid)))
  with check ((user_id = ( SELECT auth.uid() AS uid)));

alter policy "chat_messages_read" on public."chat_messages"
  using ((chat_is_member(bbl) AND ((keys ? (( SELECT auth.uid() AS uid))::text) OR (EXISTS ( SELECT 1
   FROM jsonb_object_keys(chat_messages.keys) k(k)
  WHERE starts_with(k.k, ((( SELECT auth.uid() AS uid))::text || ':'::text)))))));
