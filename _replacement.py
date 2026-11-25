        def _rebuild_fd():
            fixture_data.clear()
            for i, proj in enumerate(self.projectors):
                fixture_data.append({
                    'name':          proj.name or proj.group,
                    'fixture_type':  getattr(proj, 'fixture_type', 'PAR LED'),
                    'group':         proj.group,
                    'start_address': proj.start_address,
                    'profile':       list(self.dmx._get_profile(f"{proj.group}_{i}")),
                })

        _rebuild_fd()

        def _get_conflicts():
            occ = {}
            for i, fd in enumerate(fixture_data):
                for c in range(fd['start_address'], fd['start_address'] + len(fd['profile'])):
                    occ.setdefault(c, []).append(i)
            return {i for lst in occ.values() if len(lst) > 1 for i in lst}

        def _update_conflict_banner(conflicts):
            if conflicts and tabs.currentIndex() == 0:
                n = len(conflicts)
                conflict_banner.setText(
                    f"  ⚠  {n} fixture{'s' if n > 1 else ''} avec des canaux DMX qui se chevauchent"
                    "  -  utilisez ⚡ Auto-addr. pour corriger"
                )
                conflict_banner.setVisible(True)
            else:
                conflict_banner.setVisible(False)

        tabs.currentChanged.connect(lambda _: _update_conflict_banner(_get_conflicts()))
        def _update_chips(profile):
            while chips_vl.count():
                item = chips_vl.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            if not profile:
                return
            row_n = QWidget(); row_n.setStyleSheet("background:transparent;")
            rn = QHBoxLayout(row_n); rn.setContentsMargins(0, 0, 0, 0); rn.setSpacing(4)
            row_u = QWidget(); row_u.setStyleSheet("background:transparent;")
            ru = QHBoxLayout(row_u); ru.setContentsMargins(0, 0, 0, 0); ru.setSpacing(4)
            for ci, ch in enumerate(profile):
                col = CH_COLORS.get(ch, "#555555")
                cw = max(36, len(ch) * 7 + 14)
                chip = QLabel(ch)
                chip.setFixedSize(cw, 22)
                chip.setAlignment(Qt.AlignCenter)
                chip.setStyleSheet(
                    f"background:{col}18; color:{col}; border:1px solid {col}44;"
                    f" border-radius:4px; font-size:10px; font-weight:bold;"
                )
                chip.setToolTip(f"Canal {ci + 1}: {ch}")
                num = QLabel(str(ci + 1))
                num.setFixedWidth(cw)
                num.setAlignment(Qt.AlignCenter)
                num.setStyleSheet("color:#252525; font-size:9px; border:none; background:transparent;")
                rn.addWidget(chip); ru.addWidget(num)
            rn.addStretch(); ru.addStretch()
            chips_vl.addWidget(row_n)
            chips_vl.addWidget(row_u)
        def _populate_group_combo():
            det_group_cb.blockSignals(True)
            det_group_cb.clear()
            seen = []
            for g in list(self.GROUP_DISPLAY.keys()) + ["lyre", "barre", "strobe"]:
                if g not in seen:
                    seen.append(g)
            for fd_item in fixture_data:
                if fd_item['group'] not in seen:
                    seen.append(fd_item['group'])
            for g in seen:
                letter  = GROUP_LETTERS.get(g, "")
                name    = self.GROUP_DISPLAY.get(g, g)
                display = f"{letter}  -  {name}" if letter else name
                det_group_cb.addItem(display, g)
            det_group_cb.blockSignals(False)

        def _update_addr_range():
            if _sel[0] is None or _sel[0] >= len(fixture_data):
                return
            fd  = fixture_data[_sel[0]]
            n   = len(fd['profile'])
            end = addr_sb.value() + n - 1
            if end > 512:
                lbl_addr_range.setText(f"→ CH {end}  ⚠ dépasse 512 !")
                lbl_addr_range.setStyleSheet("color:#ff6644; font-size:12px; padding-left:6px; border:none;")
            else:
                lbl_addr_range.setText(f"→ CH {end}   ({n} canal{'x' if n > 1 else ''})")
                lbl_addr_range.setStyleSheet("color:#2a2a2a; font-size:12px; padding-left:6px; border:none;")
        def _make_card(idx):
            fd    = fixture_data[idx]
            group = fd['group']
            gc    = _GC.get(group, "#666666")
            end_ch = fd['start_address'] + len(fd['profile']) - 1
            gname  = self.GROUP_DISPLAY.get(group, group)

            card = QFrame()
            card.setFixedHeight(60)
            card.setCursor(Qt.PointingHandCursor)

            def _upd(selected, conflict):
                bg = "#10102a" if selected else "#0b0b0b"
                card.setStyleSheet(
                    f"QFrame {{ background:{bg}; border-left:4px solid {gc};"
                    f" border-top:1px solid {'#1e1e3a' if selected else '#141414'};"
                    f" border-bottom:1px solid #141414; border-right:none; border-radius:0; }}"
                )
                if hasattr(card, '_chlbl'):
                    card._chlbl.setStyleSheet(
                        f"color:{'#ff6644' if conflict else '#33ddff' if selected else '#00d4ff'};"
                        f" font-size:11px; font-weight:bold; border:none; background:transparent;"
                    )

            card._upd = _upd
            card._upd(False, False)

            hl = QHBoxLayout(card)
            hl.setContentsMargins(12, 0, 14, 0)
            hl.setSpacing(8)

            dot = QLabel("●")
            dot.setFixedWidth(13)
            dot.setAlignment(Qt.AlignCenter)
            dot.setStyleSheet("color:#1c1c1c; font-size:13px; border:none; background:transparent;")
            card._dot = dot
            card._gc  = gc
            hl.addWidget(dot)

            tv = QVBoxLayout()
            tv.setSpacing(2)
            tv.setContentsMargins(0, 0, 0, 0)
            nm = QLabel(fd['name'] or fd['group'])
            nm.setFont(QFont("Segoe UI", 11, QFont.Bold))
            nm.setStyleSheet("color:#ddd; font-size:12px; font-weight:bold; border:none; background:transparent;")
            card._namelbl = nm
            sub = QLabel(f"{fd['fixture_type']}  ·  {gname}")
            sub.setStyleSheet("color:#2e2e2e; font-size:10px; border:none; background:transparent;")
            card._sublbl = sub
            tv.addWidget(nm); tv.addWidget(sub)
            hl.addLayout(tv)
            hl.addStretch()

            chl = QLabel(f"CH {fd['start_address']}–{end_ch}")
            chl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            chl.setStyleSheet("color:#00d4ff; font-size:11px; font-weight:bold; border:none; background:transparent;")
            card._chlbl = chl
            hl.addWidget(chl)

            card.mousePressEvent = lambda e, i=idx: _select_card(i)
            return card
        def _build_cards(filter_text=""):
            while card_vl.count() > 1:
                item = card_vl.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            _cards.clear()
            ft = filter_text.strip().lower()
            conflicts = _get_conflicts()
            for idx, fd in enumerate(fixture_data):
                if ft:
                    hay = (fd['name'] + fd['fixture_type'] +
                           self.GROUP_DISPLAY.get(fd['group'], fd['group'])).lower()
                    if ft not in hay:
                        _cards.append(None)
                        continue
                card = _make_card(idx)
                card._upd(idx == _sel[0], idx in conflicts)
                _cards.append(card)
                card_vl.insertWidget(card_vl.count() - 1, card)
            n = len(fixture_data)
            lbl_cnt.setText(f"{n} fixture{'s' if n != 1 else ''}")
            _update_conflict_banner(conflicts)
        def _select_card(idx):
            if _sel[0] is not None and _sel[0] < len(_cards):
                old = _cards[_sel[0]]
                if old is not None:
                    old._upd(False, _sel[0] in _get_conflicts())
            _sel[0] = idx
            if idx is None:
                det_stack.setCurrentIndex(0)
                return
            conflicts = _get_conflicts()
            if idx < len(_cards) and _cards[idx] is not None:
                _cards[idx]._upd(True, idx in conflicts)
            det_stack.setCurrentIndex(1)
            fd = fixture_data[idx]
            gc = _GC.get(fd['group'], "#888")
            lbl_det_name.setText(fd['name'] or fd['group'])
            lbl_det_group.setText(f"  {self.GROUP_DISPLAY.get(fd['group'], fd['group'])}")
            lbl_det_group.setStyleSheet(f"color:{gc}; font-size:12px; border:none; background:transparent;")
            det_name_e.blockSignals(True);  det_name_e.setText(fd['name']);  det_name_e.blockSignals(False)
            det_type_cb.blockSignals(True)
            if fd['fixture_type'] in FIXTURE_TYPES:
                det_type_cb.setCurrentIndex(FIXTURE_TYPES.index(fd['fixture_type']))
            det_type_cb.blockSignals(False)
            _populate_group_combo()
            det_group_cb.blockSignals(True)
            for i in range(det_group_cb.count()):
                if det_group_cb.itemData(i) == fd['group']:
                    det_group_cb.setCurrentIndex(i); break
            det_group_cb.blockSignals(False)
            addr_sb.blockSignals(True);  addr_sb.setValue(fd['start_address']);  addr_sb.blockSignals(False)
            _update_addr_range()
            det_profile_cb.blockSignals(True)
            pn = profile_name(fd['profile'])
            if pn:
                pi = det_profile_cb.findData(pn)
                if pi >= 0:
                    det_profile_cb.setCurrentIndex(pi)
            else:
                det_profile_cb.setCurrentIndex(det_profile_cb.findData("__custom__"))
            det_profile_cb.blockSignals(False)
            _update_chips(fd['profile'])
            if idx in conflicts:
                others = []
                for j, fd2 in enumerate(fixture_data):
                    if j == idx: continue
                    s1, e1 = fd['start_address'], fd['start_address'] + len(fd['profile']) - 1
                    s2, e2 = fd2['start_address'], fd2['start_address'] + len(fd2['profile']) - 1
                    if s1 <= e2 and s2 <= e1:
                        others.append(fd2['name'] or fd2['group'])
                lbl_conflict_det.setText(f"⚠  Chevauchement avec : {", ".join(others)}")
                lbl_conflict_det.setVisible(True)
            else:
                lbl_conflict_det.setVisible(False)
            if idx < len(_cards) and _cards[idx] is not None:
                scroll.ensureWidgetVisible(_cards[idx])
        def _commit():
            idx = _sel[0]
            if idx is None or idx >= len(fixture_data): return
            fd   = fixture_data[idx]
            proj = self.projectors[idx]
            fd['name']          = det_name_e.text().strip() or fd['group']
            fd['fixture_type']  = det_type_cb.currentText()
            fd['group']         = det_group_cb.currentData() or fd['group']
            fd['start_address'] = addr_sb.value()
            proj.name           = fd['name']
            proj.fixture_type   = fd['fixture_type']
            proj.group          = fd['group']
            proj.start_address  = fd['start_address']
            self._rebuild_dmx_patch()
            self.save_dmx_patch_config()
            conflicts = _get_conflicts()
            _update_conflict_banner(conflicts)
            if idx < len(_cards) and _cards[idx] is not None:
                card = _cards[idx]
                card._namelbl.setText(fd['name'])
                card._sublbl.setText(
                    f"{fd['fixture_type']}  ·  {self.GROUP_DISPLAY.get(fd['group'], fd['group'])}"
                )
                end_ch = fd['start_address'] + len(fd['profile']) - 1
                card._chlbl.setText(f"CH {fd['start_address']}–{end_ch}")
                card._upd(True, idx in conflicts)
            lbl_det_name.setText(fd['name'])
            gc = _GC.get(fd['group'], "#888")
            lbl_det_group.setText(f"  {self.GROUP_DISPLAY.get(fd['group'], fd['group'])}")
            lbl_det_group.setStyleSheet(f"color:{gc}; font-size:12px; border:none; background:transparent;")
            _update_addr_range()
            if idx in conflicts:
                others = []
                for j, fd2 in enumerate(fixture_data):
                    if j == idx: continue
                    s1, e1 = fd['start_address'], fd['start_address'] + len(fd['profile']) - 1
                    s2, e2 = fd2['start_address'], fd2['start_address'] + len(fd2['profile']) - 1
                    if s1 <= e2 and s2 <= e1:
                        others.append(fd2['name'] or fd2['group'])
                lbl_conflict_det.setText(f"⚠  Chevauchement avec : {", ".join(others)}")
                lbl_conflict_det.setVisible(True)
            else:
                lbl_conflict_det.setVisible(False)
        _name_tmr = QTimer(dialog)
        _name_tmr.setSingleShot(True)
        _name_tmr.setInterval(500)
        _name_tmr.timeout.connect(_commit)
        det_name_e.textChanged.connect(lambda _: _name_tmr.start())
        det_type_cb.currentIndexChanged.connect(lambda _: _commit())
        det_group_cb.currentIndexChanged.connect(lambda _: _commit())
        addr_sb.valueChanged.connect(lambda _: (_update_addr_range(), _commit()))
        btn_am.clicked.connect(lambda: addr_sb.setValue(max(1, addr_sb.value() - 1)))
        btn_ap.clicked.connect(lambda: addr_sb.setValue(min(512, addr_sb.value() + 1)))

        def _on_profile_changed(_):
            data = det_profile_cb.currentData()
            i = _sel[0]
            if i is None or i >= len(fixture_data): return
            if data == "__custom__":
                custom = self._show_custom_profile_dialog(fixture_data[i]['profile'])
                if custom:
                    fixture_data[i]['profile'] = custom
                prev = profile_name(fixture_data[i]['profile'])
                pi2  = det_profile_cb.findData(prev) if prev else -1
                det_profile_cb.blockSignals(True)
                det_profile_cb.setCurrentIndex(pi2 if pi2 >= 0 else det_profile_cb.findData("__custom__"))
                det_profile_cb.blockSignals(False)
            elif data in DMX_PROFILES:
                fixture_data[i]['profile'] = list(DMX_PROFILES[data])
            self._rebuild_dmx_patch()
            self.save_dmx_patch_config()
            _update_chips(fixture_data[i]['profile'])
            _update_addr_range()
            conflicts = _get_conflicts()
            _update_conflict_banner(conflicts)
            if i < len(_cards) and _cards[i] is not None:
                end_ch = fixture_data[i]['start_address'] + len(fixture_data[i]['profile']) - 1
                _cards[i]._chlbl.setText(f"CH {fixture_data[i]['start_address']}–{end_ch}")
                _cards[i]._upd(True, i in conflicts)

        det_profile_cb.currentIndexChanged.connect(_on_profile_changed)
        def _del_selected():
            idx = _sel[0]
            if idx is None or idx >= len(fixture_data): return
            fname = fixture_data[idx]['name']
            if QMessageBox.question(
                dialog, "Supprimer", f"Supprimer « {fname} » ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            fixture_data.pop(idx)
            if 0 <= idx < len(self.projectors):
                self.projectors.pop(idx)
            _sel[0] = None
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _build_cards(filter_bar.text())
            det_stack.setCurrentIndex(0)

        btn_det_del.clicked.connect(_del_selected)

        def _update_dots():
            for i, card in enumerate(_cards):
                if card is None or i >= len(self.projectors): continue
                proj = self.projectors[i]
                if proj.muted or proj.level == 0:
                    col = "#1c1c1c"
                else:
                    col = proj.color.name() if hasattr(proj, 'color') and proj.color.isValid() else card._gc
                card._dot.setStyleSheet(
                    f"color:{col}; font-size:13px; border:none; background:transparent;"
                )
        def _add_fixture():
            preset = self._show_fixture_library_dialog()
            if not preset: return
            _CH = {"PAR LED": 5, "Moving Head": 8, "Barre LED": 5,
                   "Stroboscope": 2, "Machine a fumee": 2}
            next_addr = 1
            if self.projectors:
                last = max(self.projectors, key=lambda p: p.start_address)
                next_addr = last.start_address + _CH.get(getattr(last, 'fixture_type', 'PAR LED'), 5)
            p = Projector(
                preset.get('group', 'face'),
                name=preset.get('name', 'Fixture'),
                fixture_type=preset.get('fixture_type', 'PAR LED')
            )
            p.start_address = next_addr
            p.canvas_x = 0.5; p.canvas_y = 0.5
            if p.fixture_type == "Machine a fumee":
                p.fan_speed = 0
            self.projectors.append(p)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            new_idx = len(fixture_data) - 1
            _build_cards(filter_bar.text())
            _select_card(new_idx)
        def _auto_address():
            if QMessageBox.question(
                dialog, "Auto-adresser",
                "Recalculer automatiquement toutes les adresses DMX ?\n"
                "Les adresses seront réassignées de façon continue, sans espaces.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            addr = 1
            for fd in fixture_data:
                fd['start_address'] = addr
                addr += len(fd['profile'])
                if addr > 512: addr = 512
            for proj, fd in zip(self.projectors, fixture_data):
                proj.start_address = fd['start_address']
            self._rebuild_dmx_patch()
            self.save_dmx_patch_config()
            cur = _sel[0]
            _build_cards(filter_bar.text())
            if cur is not None: _select_card(cur)
        def _reset_defaults():
            if QMessageBox.question(
                dialog, "Réinitialiser",
                "Réinitialiser les fixtures par défaut ?\nToutes les modifications seront perdues.",
                QMessageBox.Yes | QMessageBox.No
            ) != QMessageBox.Yes: return
            self.projectors.clear()
            addr = 1
            for name, ftype, group in self._DEFAULT_FIXTURES:
                p = Projector(group, name=name, fixture_type=ftype)
                profile = list(DMX_PROFILES["2CH_FUMEE"] if group == "fumee" else DMX_PROFILES["RGBDS"])
                p.start_address = addr
                addr += len(profile)
                self.projectors.append(p)
            self.projectors[-1].fan_speed = 0
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _sel[0] = None
            _build_cards()
            det_stack.setCurrentIndex(0)
        def _open_wizard():
            if self.projectors:
                if QMessageBox.question(
                    dialog, "Nouveau plan de feu",
                    f"Cette action remplacera les {len(self.projectors)} fixture(s) existante(s).\n"
                    "Continuer vers l'assistant ?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                ) != QMessageBox.Yes: return
            wiz = NewPlanWizard(dialog)
            if wiz.exec() != QDialog.Accepted: return
            fixtures = wiz.get_result()
            if not fixtures: return
            self.projectors.clear()
            for fdd in fixtures:
                p = Projector(fdd['group'], name=fdd['name'], fixture_type=fdd['fixture_type'])
                p.start_address = fdd['start_address']
                p.canvas_x = None; p.canvas_y = None
                if fdd['fixture_type'] == "Machine a fumee":
                    p.fan_speed = 0
                self.projectors.append(p)
            self._rebuild_dmx_patch()
            _rebuild_fd()
            _sel[0] = None
            _build_cards()
            det_stack.setCurrentIndex(0)

        btn_new.clicked.connect(_open_wizard)
        btn_add.clicked.connect(_add_fixture)
        btn_auto_l.clicked.connect(_auto_address)
        btn_dflt_l.clicked.connect(_reset_defaults)
        filter_bar.textChanged.connect(lambda txt: _build_cards(txt))
        def _get_selected_projs():
            if not proxy.selected_lamps:
                return list(self.projectors)
            g_cnt = {}; result = []
            for proj in self.projectors:
                li = g_cnt.get(proj.group, 0)
                if (proj.group, li) in proxy.selected_lamps:
                    result.append(proj)
                g_cnt[proj.group] = li + 1
            return result if result else list(self.projectors)

        def _align_grid():
            projs = _get_selected_projs(); n = len(projs)
            if not n: return
            cols = max(1, round(n ** 0.5)); rows = (n + cols - 1) // cols; mg = 0.12
            for i, proj in enumerate(projs):
                c = i % cols; r = i // cols
                proj.canvas_x = 0.5 if cols == 1 else mg + c * (1 - 2*mg) / (cols - 1)
                proj.canvas_y = 0.5 if rows == 1 else mg + r * (1 - 2*mg) / (rows - 1)
            canvas.update(); self.save_dmx_patch_config()

        def _center_h():
            for p in _get_selected_projs(): p.canvas_x = 0.5
            canvas.update(); self.save_dmx_patch_config()

        def _center_v():
            for p in _get_selected_projs(): p.canvas_y = 0.5
            canvas.update(); self.save_dmx_patch_config()

        def _distribute_h():
            projs = _get_selected_projs(); n = len(projs)
            if n < 2: return; mg = 0.10
            for i, p in enumerate(sorted(projs, key=lambda x: getattr(x, 'canvas_x', 0.5) or 0.5)):
                p.canvas_x = mg + i * (1 - 2*mg) / (n - 1)
            canvas.update(); self.save_dmx_patch_config()

        def _distribute_v():
            projs = _get_selected_projs(); n = len(projs)
            if n < 2: return; mg = 0.10
            for i, p in enumerate(sorted(projs, key=lambda x: getattr(x, 'canvas_y', 0.5) or 0.5)):
                p.canvas_y = mg + i * (1 - 2*mg) / (n - 1)
            canvas.update(); self.save_dmx_patch_config()

        btn_ag.clicked.connect(_align_grid); btn_ch.clicked.connect(_center_h)
        btn_cv.clicked.connect(_center_v);   btn_dh.clicked.connect(_distribute_h)
        btn_dv.clicked.connect(_distribute_v)
        def _select_all_canvas():
            g_cnt = {}
            for p in self.projectors:
                li = g_cnt.get(p.group, 0)
                proxy.selected_lamps.add((p.group, li)); g_cnt[p.group] = li + 1
            canvas.update()

        def _deselect_canvas():
            proxy.selected_lamps.clear(); canvas.update()

        def _show_groups_popup():
            _MS = ("QMenu{background:#1e1e1e;border:1px solid #3a3a3a;border-radius:6px;"
                   "padding:6px;color:white;font-size:11px;}"
                   "QMenu::item{padding:6px 20px;border-radius:3px;}"
                   "QMenu::item:selected{background:#333;}")
            m = QMenu(btn_groups_c); m.setStyleSheet(_MS)
            seen = []
            for p in self.projectors:
                if p.group not in seen: seen.append(p.group)
            if not seen: return
            for g in seen:
                act = m.addAction(self.GROUP_DISPLAY.get(g, g))
                act.triggered.connect(lambda checked, grp=g: _sel_group_canvas(grp))
            m.exec(btn_groups_c.mapToGlobal(QPoint(0, btn_groups_c.height())))

        def _sel_group_canvas(grp):
            g_cnt = {}
            for p in self.projectors:
                li = g_cnt.get(p.group, 0)
                if p.group == grp: proxy.selected_lamps.add((p.group, li))
                g_cnt[p.group] = li + 1
            canvas.update()
        def _delete_canvas_selection():
            n = len(proxy.selected_lamps)
            if not n: return
            if QMessageBox.question(
                dialog, "Supprimer",
                f"Supprimer {n} fixture{'s' if n > 1 else ''} sélectionnée{'s' if n > 1 else ''} ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            g_cnt = {}; to_rm = set()
            for i, proj in enumerate(self.projectors):
                li = g_cnt.get(proj.group, 0)
                if (proj.group, li) in proxy.selected_lamps: to_rm.add(i)
                g_cnt[proj.group] = li + 1
            for i in sorted(to_rm, reverse=True): self.projectors.pop(i)
            proxy.selected_lamps.clear()
            self._rebuild_dmx_patch(); _rebuild_fd()
            _build_cards(filter_bar.text()); canvas.update()

        def _reset_canvas_positions():
            if QMessageBox.question(
                dialog, "Réinitialiser les positions",
                "Remettre toutes les fixtures à leur position automatique ?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes: return
            for proj in self.projectors: proj.canvas_x = None; proj.canvas_y = None
            self.save_dmx_patch_config(); canvas.update()
        btn_sel_all_c.clicked.connect(_select_all_canvas)
        btn_desel_c.clicked.connect(_deselect_canvas)
        btn_groups_c.clicked.connect(_show_groups_popup)
        btn_del_sel_c.clicked.connect(_delete_canvas_selection)
        btn_reset_pos_c.clicked.connect(_reset_canvas_positions)

        proxy._add_cb        = _add_fixture
        proxy._wizard_cb     = _open_wizard
        proxy._align_grid_cb = _align_grid
        proxy._center_h_cb   = _center_h
        proxy._center_v_cb   = _center_v
        proxy._distrib_h_cb  = _distribute_h
        proxy._distrib_v_cb  = _distribute_v

        canvas_timer = QTimer(dialog)

        def _timer_tick():
            canvas.update()
            _update_dots()

        canvas_timer.timeout.connect(_timer_tick)
        canvas_timer.start(80)
        _build_cards()
        if fixture_data:
            _select_card(0)

        dialog.exec()