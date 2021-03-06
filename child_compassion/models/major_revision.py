# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2016 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Emanuel Cino <ecino@compassion.ch>
#
#    The licence is in the file __openerp__.py
#
##############################################################################


from openerp import api, models, fields


class MajorRevision(models.Model):
    _inherit = 'translatable.model'
    _name = 'compassion.major.revision'

    name = fields.Selection([
        # Child major revision
        ('Birthdate', 'Birthdate'),
        ('Chronic Disabilities', 'Chronic Disabilities'),
        ('Chronic Illness', 'Chronic Illness'),
        ('First Name', 'First Name'),
        ('Formal Education Level', 'Formal Education Level'),
        ('Gender', 'Gender'),
        ('Last Name', 'Last Name'),
        ('Planned Completion Date', 'Planned Completion Date'),
        ('Preferred Name', 'Preferred Name'),
        # Household major revision TODO Verify values
        ('Natural Father Alive', 'Natural Father Alive'),
        ('Natural Mother Alive', 'Natural Mother Alive'),
        ('Primary Caregiver', 'Primary Caregiver'),
    ], required=True)
    old_value = fields.Char()
    child_id = fields.Many2one('compassion.child')
    household_id = fields.Many2one('compassion.household')

    @api.model
    def create(self, vals):
        major_field = super(MajorRevision, self).create(vals)
        major_field.old_value = major_field.get_field_value()
        return major_field

    @api.model
    def get_field_mapping(self):
        return {
            'Birthdate': 'birthdate',
            'Chronic Disabilities': 'physical_disability_ids.value',
            'Chronic Illness': 'chronic_illness_ids.value',
            'First Name': 'firstname',
            'Formal Education Level': 'formal_education',
            'Gender': 'gender',
            'Last Name': 'lastname',
            'Planned Completion Date': 'completion_date',
            'Preferred Name': 'preferred_name',
            'Natural Father Alive': 'father_alive',
            'Natural Mother Alive': 'mother_alive',
            'Primary Caregiver': 'primary_caregiver',
        }

    @api.multi
    def get_field_value(self):
        values = list()
        for revision in self:
            field_mapping = revision.get_field_mapping()
            res_object = revision.child_id or revision.household_id
            if res_object:
                values.extend(res_object.mapped(field_mapping[revision.name]))
        return ', '.join(map(str, values))
