# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from datetime import date

class TestRadiologySlotWizard(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.patient = cls.env['res.partner'].create({
            'name': 'John Doe',
            'is_patient': True,
        })
        cls.radiologist = cls.env['res.partner'].create({
            'name': 'Dr. Smith',
            'is_radiologist': True,
        })
        cls.resource = cls.env['resource.resource'].create({
            'name': 'MRI Machine',
            'resource_type': 'material',
        })
        # Creates working hours config; auto-populates lines for all days
        cls.working_hours = cls.env['radiology.working.hours'].create({
            'name': 'MRI Working Hours',
            'resource_id': cls.resource.id,
            'radiologist_id': cls.radiologist.id,
            'slot_duration': 1.0,
            'active': True,
        })
        # 2 shifts per day (morning + evening) for 7 days, except Sunday has no evening = 13
        assert len(cls.working_hours.line_ids) == 13, "Should have 13 working hours lines"

    def test_slot_wizard_one_click_booking(self):
        """Clicking 'Book This Slot' on any slot row books it immediately."""
        wizard = self.env['radiology.slot.wizard'].create({
            'patient_id': self.patient.id,
            'radiologist_id': self.radiologist.id,
            'resource_id': self.resource.id,
            'date': date(2026, 6, 8),  # Monday
        })
        wizard._generate_slots()  # Mirrors what all openers now do explicitly

        self.assertTrue(wizard.slot_ids, "Slots should be populated")
        # Monday: morning 8-14, evening 14-20 → 12 x 1h slots
        self.assertEqual(len(wizard.slot_ids), 12)

        # Pick the 3rd slot (10:00-11:00) via one-click booking
        slots_sorted = wizard.slot_ids.sorted('slot_start')
        third_slot = slots_sorted[2]

        self.assertEqual(third_slot.slot_start.hour, 10)
        self.assertEqual(third_slot.slot_end.hour, 11)

        # Simulate one-click: action_select_and_book on the line
        action = third_slot.action_select_and_book()

        appointment_id = action.get('res_id')
        appointment = self.env['radiology.appointment'].browse(appointment_id)

        self.assertEqual(appointment.start, third_slot.slot_start,
                         "Booked start should match selected slot")
        self.assertEqual(appointment.stop, third_slot.slot_end,
                         "Booked end should match selected slot")
        self.assertEqual(appointment.state, 'scheduled')

    def test_fields_not_readonly_in_python(self):
        """Ensure slot line fields are writable so values are stored in the DB."""
        self.assertFalse(
            self.env['radiology.slot.wizard.line']._fields['slot_start'].readonly,
            "slot_start should not be readonly in Python")
        self.assertFalse(
            self.env['radiology.slot.wizard.line']._fields['slot_end'].readonly,
            "slot_end should not be readonly in Python")
        self.assertFalse(
            self.env['radiology.slot.wizard.line']._fields['resource_id'].readonly,
            "resource_id should not be readonly in Python")
        self.assertFalse(
            self.env['radiology.slot.wizard']._fields['next_available_date'].readonly,
            "next_available_date should not be readonly in Python")

    def test_no_selected_field(self):
        """Ensure the 'selected' checkbox field has been removed from the line model."""
        self.assertNotIn(
            'selected',
            self.env['radiology.slot.wizard.line']._fields,
            "The 'selected' field should no longer exist on slot lines")
