# -*- encoding: utf-8 -*-
##############################################################################
#
#    Copyright (C) 2014-2015 Compassion CH (http://www.compassion.ch)
#    Releasing children from poverty in Jesus' name
#    @author: Cyril Sester, Emanuel Cino
#
#    The licence is in the file __openerp__.py
#
##############################################################################

from openerp import api, exceptions, fields, models, _
from openerp.tools import DEFAULT_SERVER_DATE_FORMAT as DF

from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from lxml import etree
import csv
import os

from .product import GIFT_CATEGORY, SPONSORSHIP_CATEGORY, FUND_CATEGORY
import logging
logger = logging.getLogger(__name__)
THIS_DIR = os.path.dirname(__file__)


class sponsorship_line(models.Model):
    _inherit = 'recurring.contract.line'

    sponsorship_id = fields.Many2one(
        'recurring.contract', 'Sponsorship')

    @api.v7
    def fields_view_get(self, cr, uid, view_id=None, view_type='tree',
                        context=None, toolbar=False, submenu=False):
        """ Change product domain depending on contract type. """
        res = super(sponsorship_line, self).fields_view_get(
            cr, uid, view_id, view_type, context, toolbar, submenu)

        if view_type == 'tree':
            type = context.get('default_type', 'O')
            if 'S' in type:
                res['fields']['product_id']['domain'] = [
                    ('categ_name', 'in', [SPONSORSHIP_CATEGORY,
                                          FUND_CATEGORY])]
                # Remove field sponsorship_id for sponsorship contracts
                doc = etree.XML(res['arch'])
                for node in doc.xpath("//field[@name='sponsorship_id']"):
                    node.getparent().remove(node)
                res['arch'] = etree.tostring(doc)
                del(res['fields']['sponsorship_id'])
            else:
                res['fields']['product_id']['domain'] = [
                    ('categ_name', '!=', SPONSORSHIP_CATEGORY)]

        return res


class SponsorshipContract(models.Model):
    _inherit = 'recurring.contract'

    ##########################################################################
    #                                 FIELDS                                 #
    ##########################################################################

    correspondant_id = fields.Many2one(
        'res.partner', string='Correspondant', readonly=True,
        states={'draft': [('readonly', False)],
                'waiting': [('readonly', False)],
                'mandate': [('readonly', False)]},
        track_visibility='onchange')
    partner_codega = fields.Char(
        'Partner ref', related='correspondant_id.ref', readonly=True)
    fully_managed = fields.Boolean(
        compute='_is_fully_managed', store=True)
    birthday_invoice = fields.Float("Annual birthday gift", help=_(
        "Set the amount to enable automatic invoice creation each year "
        "for a birthday gift. The invoice is set two months before "
        "child's birthday."), track_visibility='onchange')
    contract_line_ids = fields.One2many(default=lambda self:
                                        self._get_standard_lines())
    reading_language = fields.Many2one(
        'res.lang.compassion', 'Preferred language', required=False)

    global_id = fields.Char()

    ##########################################################################
    #                             FIELDS METHODS                             #
    ##########################################################################

    @api.model
    def get_ending_reasons(self):
        res = super(SponsorshipContract, self).get_ending_reasons()
        context = self.env.context
        if 'active_id' in context and \
                context.get('active_model') == self._name:
            type = self.browse(context['active_id']).type
        else:
            type = context.get('default_type', 'O')
        if 'S' in type:
            res.extend([
                ('1', _("Depart of child")),
                ('10', _("Subreject")),
                ('11', _("Exchange of sponsor"))
            ])
            res.sort(key=lambda tup: int(float(tup[0])))  # Sort res
        return res

    @api.model
    def _get_sponsorship_standard_lines(self):
        """ Select Sponsorship and General Fund by default """
        res = []
        product_obj = self.env['product.product'].with_context(lang='en_US')
        sponsorship_id = product_obj.search(
            [('name', '=', 'Sponsorship')])[0].id
        gen_id = product_obj.search(
            [('name', '=', 'General Fund')])[0].id
        sponsorship_vals = {
            'product_id': sponsorship_id,
            'quantity': 1,
            'amount': 42,
            'subtotal': 42
        }
        gen_vals = {
            'product_id': gen_id,
            'quantity': 1,
            'amount': 8,
            'subtotal': 8
        }
        res.append([0, 6, sponsorship_vals])
        res.append([0, 6, gen_vals])
        return res

    @api.model
    def _get_standard_lines(self):
        if 'S' in self.env.context.get('default_type', 'O'):
            return self._get_sponsorship_standard_lines()
        return []

    @api.multi
    @api.depends('partner_id', 'correspondant_id')
    def _is_fully_managed(self):
        """Tells if the correspondent and the payer is the same person."""
        for contract in self:
            contract.fully_managed = (contract.partner_id ==
                                      contract.correspondant_id)

    @api.model
    def _get_type(self):
        res = super(SponsorshipContract, self)._get_type()
        res.extend([
            ('G', _('Child Gift')),
            ('S', _('Sponsorship')),
            ('SC', _('Correspondence'))])
        return res

    @api.one
    def _get_last_paid_invoice(self):
        """ Override to exclude gift invoices. """
        self.last_paid_invoice_date = max(
            self.invoice_line_ids.filtered(
                lambda l: l.state == 'paid' and
                l.product_id.categ_name != GIFT_CATEGORY).mapped(
                    'invoice_id.date_invoice') or [False])

    ##########################################################################
    #                              ORM METHODS                               #
    ##########################################################################

    @api.model
    def create(self, vals):
        """ Perform various checks on contract creations
        """
        child = self.env['compassion.child'].browse(vals.get('child_id'))
        if 'S' in vals.get('type', '') and child:
            child.write(
                {'sponsor_id': vals['partner_id'],
                 'delegated_to': False, 'delegated_comment': False,
                 'date_delegation': False, 'date_end_delegation': False}
            )

        return super(SponsorshipContract, self).create(vals)

    @api.multi
    def write(self, vals):
        """ Perform various checks on contract modification """
        if 'child_id' in vals:
            self._on_change_child_id(vals)

        return super(SponsorshipContract, self).write(vals)

    @api.multi
    def unlink(self):
        for contract in self:
            # We can only delete draft sponsorships.
            if 'S' in contract.type and contract.state != 'draft':
                raise exceptions.Warning(_('Warning'),
                                         _('You cannot delete a validated '
                                           'sponsorship.'))
            # Remove sponsor of child
            if 'S' in contract.type and contract.child_id:
                child_sponsor_id = contract.child_id.sponsor_id and \
                    contract.child_id.sponsor_id.id
                if child_sponsor_id == contract.correspondant_id.id:
                    contract.child_id.write({'sponsor_id': False})
        return super(SponsorshipContract, self).unlink()

    ##########################################################################
    #                             PUBLIC METHODS                             #
    ##########################################################################
    def clean_invoices_paid(self, since_date=None, to_date=None, gifts=False,
                            keep_lines=None):
        """ Removes or cancel paid invoices in the given period.

        - The process bypasses the ORM by directly removing the invoice_lines
          concerning the given contracts. It also splits the sponsor's
          payment in order to be able to change the attribution of the amount
          that was destined to the cancelled contract.

        Note: direct access to database avoids to unreconcile and reconcile
              again invoices, which is a huge performance gain.
        """
        # Find all paid invoice lines after the given date
        inv_line_obj = self.env['account.invoice.line']
        invl_search = self._filter_clean_invoices(since_date, to_date, gifts)
        inv_lines = inv_line_obj.search(invl_search)

        # Invoice and move lines that need to be removed/updated
        to_remove_inv = set()
        to_update_inv = set()
        to_remove_mvl = list()
        to_remove_move = list()
        # Dictionary containing the total debit_lines in account 1050
        # for each invoice. These lines will be updated.
        # dict of format {move_line_id: debit_amount}
        to_update_mvl = dict()
        # Dictionary containing payment move_lines that need to be splitted
        # dict of format {move_line_id: amount_removed}
        split_payment_mvl = dict()
        unrec_pml = list()

        # Store data that is removed to pass it in sub_modules
        # Dictionary is in the following format :
        # {invoice_line_id: [invoice_id, child_code, product_name, amount]}
        invl_rm_data = dict()

        # 1. Determine which action has to be done for each invoice_line
        self._how_to_clean_invl(
            inv_lines, to_remove_inv, to_update_inv,
            to_remove_mvl, to_remove_move, to_update_mvl, split_payment_mvl,
            unrec_pml, invl_rm_data)
        # 2. Manually remove invoice_lines, move_lines, empty invoices/moves
        #    and reconcile refs that are no longer valid
        if inv_lines:
            # Call the hook for letting other modules handle the removal.
            self._on_invoice_line_removal(invl_rm_data)

            self._clean_paid_invoice_lines(list(to_remove_inv),
                                           list(to_update_inv),
                                           inv_lines.ids,
                                           keep_lines)

            self._clean_move_lines(to_remove_mvl, to_remove_move,
                                   to_update_mvl)

            # Update the total field of invoices
            self.env['account.invoice'].browse(
                list(to_update_inv)).button_compute(set_total=True)

            # 2.2. Split or unreconcile payment so that the amount deleted is
            #      isolated.
            self._unrec_split_payment(split_payment_mvl, unrec_pml)

        return True

    @api.model
    def _on_invoice_line_removal(self, invl_rm_data):
        pass

    @api.multi
    def suspend_contract(self):
        """
        If ir.config.parameter is set : change sponsorship invoices with
        a fund donation set in the config.
        Otherwise, Cancel the number of invoices specified starting
        from a given date. This is useful to suspend a contract for a given
        period."""
        date_start = datetime.today().strftime(DF)

        config_obj = self.env['ir.config_parameter']
        suspend_config = config_obj.search(
            [('key', '=', 'sponsorship_compassion.suspend_product_id')])
        # Cancel invoices in the period of suspension
        self._clean_invoices(
            date_start, keep_lines=_('Center suspended'))

        for contract in self:
            # Add a note in the contract and in the partner.
            project_code = contract.child_id.project_id.icp_id
            contract.message_post(
                "The project {0} was suspended and funds are retained."
                "<br/>Invoices due in the suspension period "
                "are automatically cancelled.".format(
                    project_code),
                "Project Suspended", 'comment')
            contract.partner_id.message_post(
                "The project {0} was suspended and funds are retained "
                "for child {1}. <b>"
                "<br/>Invoices due in the suspension period "
                "are automatically cancelled.".format(
                    project_code, contract.child_code),
                "Project Suspended", 'comment')

        # Change invoices if config tells to do so.
        if suspend_config:
            product_id = int(suspend_config[0].value)
            self._suspend_change_invoices(date_start,
                                          product_id)

        return True

    @api.multi
    def _suspend_change_invoices(self, since_date, product_id):
        """ Change cancelled sponsorship invoices and put them for given
        product. Re-open invoices. """
        cancel_inv_lines = self.env['account.invoice.line'].with_context(
            lang='en_US').search([
                ('contract_id', 'in', self.ids),
                ('state', '=', 'cancel'),
                ('product_id.categ_name', '=', SPONSORSHIP_CATEGORY),
                ('due_date', '>=', since_date)])
        invoices = cancel_inv_lines.mapped('invoice_id')
        invoices.action_cancel_draft()
        vals = self.get_suspend_invl_data(product_id)
        cancel_inv_lines.write(vals)
        invoices.signal_workflow('invoice_open')

    @api.multi
    def get_suspend_invl_data(self, product_id):
        """ Returns invoice_line data for a given product when center
        is suspended. """

        product = self.env['product.product'].browse(product_id)
        vals = {
            'product_id': product_id,
            'account_id': product.property_account_income.id,
            'name': 'Replacement of sponsorship (fund-suspended)'}
        rec = self.env['account.analytic.default'].account_get(product.id)
        if rec and rec.analytic_id:
            vals['account_analytic_id'] = rec.analytic_id.id

        return vals

    @api.multi
    def reactivate_contract(self):
        """ When project is reactivated, we re-open cancelled invoices,
        or we change open invoices if fund is set to replace sponsorship
        product. We also change attribution of invoices paid in advance.
        """
        date_start = datetime.today().strftime(DF)
        config_obj = self.env['ir.config_parameter']
        suspend_config = config_obj.search(
            [('key', '=', 'sponsorship_compassion.suspend_product_id')],
            limit=1)
        invl_obj = self.env['account.invoice.line']
        sponsorship_product = self.env['product.product'].with_context(
            lang='en_US').search([('name', '=', 'Sponsorship')])
        contracts = None
        if suspend_config:
            # Revert future invoices with sponsorship product
            susp_product_id = int(suspend_config.value)
            invl_lines = invl_obj.search([
                ('contract_id', 'in', self.ids),
                ('product_id', '=', susp_product_id),
                ('state', 'in', ['open', 'paid']),
                ('due_date', '>=', date_start)])
            invl_data = {
                'product_id': sponsorship_product.id,
                'account_id': sponsorship_product.property_account_income.id,
                'name': sponsorship_product.name
            }
            rec = self.env['account.analytic.default'].account_get(
                sponsorship_product.id)
            if rec and rec.analytic_id:
                invl_data['account_analytic_id'] = rec.analytic_id.id
            invl_lines.write(invl_data)

            invoices = invl_lines.mapped('invoice_id')
            contracts = invl_lines.mapped('contract_id')
            mvls_paid = invoices.filtered(
                lambda inv: inv.state == 'paid').mapped(
                'payment_ids.reconcile_id.line_id')

            # Unreconcile paid invoices
            mvls_paid._remove_move_reconcile()
            # Cancel and confirm again invoices to update move lines
            invoices.action_cancel()
            invoices.action_cancel_draft()
            invoices.signal_workflow('invoice_open')
        else:
            # Open again cancelled invoices
            inv_lines = invl_obj.search([
                ('contract_id', 'in', self.ids),
                ('product_id', '=', sponsorship_product.id),
                ('state', '=', 'cancel'),
                ('due_date', '>=', date_start)])
            contracts = inv_lines.mapped('contract_id')

            for invoice in inv_lines.mapped('invoice_id').filtered(
                    lambda inv: inv.state == 'cancel'):
                invoice.action_cancel_draft()
                invoice.signal_workflow('invoice_open')

        # Log a note in the contracts
        for contract in contracts:
            contract.message_post(
                "The project was reactivated."
                "<br/>Invoices due in the suspension period "
                "are automatically reverted.",
                "Project Reactivated", 'comment')

    ##########################################################################
    #                             VIEW CALLBACKS                             #
    ##########################################################################
    @api.v7
    def fields_view_get(self, cr, uid, view_id=None, view_type='form',
                        context=None, toolbar=False, submenu=False):
        """ Display only contract type needed in view. """
        res = super(SponsorshipContract, self).fields_view_get(
            cr, uid, view_id, view_type, context, toolbar, submenu)

        if view_type == 'form' and (isinstance(res['fields'], dict) and
                                    'type' in res['fields']):
            if 'S' in context.get('default_type', 'O'):
                # Remove non sponsorship types
                res['fields']['type']['selection'].pop(0)
                res['fields']['type']['selection'].pop(0)
            else:
                # Remove type Sponsorships so that we cannot change to it.
                res['fields']['type']['selection'].pop(2)
                res['fields']['type']['selection'].pop(2)
        return res

    @api.one
    @api.onchange('partner_id')
    def on_change_partner_id(self):
        super(SponsorshipContract, self).on_change_partner_id()
        if 'S' in self.type and self.state == 'draft':
            # If state draft correspondant_id=partner_id
            self.correspondant_id = self.partner_id

    ##########################################################################
    #                            WORKFLOW METHODS                            #
    ##########################################################################
    @api.multi
    def contract_cancelled(self):
        res = super(SponsorshipContract, self).contract_cancelled()

        self.filtered(lambda c: c.type == 'S')._on_sponsorship_finished()

        return res

    @api.multi
    def contract_terminated(self):
        res = super(SponsorshipContract, self).contract_terminated()

        self.filtered(lambda c: c.type == 'S')._on_sponsorship_finished()

        return res

    @api.multi
    def contract_waiting(self):
        for contract in self.with_context(lang='en_US'):
            if contract.type == 'G':
                # Activate directly if sponsorship is already active
                for line in contract.contract_line_ids:
                    sponsorship = line.sponsorship_id
                    if sponsorship.state == 'active':
                        self.env.cr.execute(
                            "update recurring_contract set "
                            "activation_date = current_date,is_active = True "
                            "where id = %s", [contract.id])
                        self.env.invalidate_all()
            elif contract.type == 'SC':
                # Activate directly correspondence sponsorships
                self.env.cr.execute(
                    "update recurring_contract set "
                    "activation_date = current_date,is_active = True "
                    "where id = %s", [contract.id])
                self.env.invalidate_all()

        return super(SponsorshipContract, self).contract_waiting()

    ##########################################################################
    #                             PRIVATE METHODS                            #
    ##########################################################################
    @api.multi
    def _clean_invoices(self, since_date=None, to_date=None,
                        keep_lines=None, clean_invoices_paid=True):
        """ Take into consideration when the sponsor has paid in advance,
        so that we cancel/modify the paid invoices and let the user decide
        what to do with the payment.
        """
        if clean_invoices_paid:
            sponsorships = self.filtered(lambda s: s.type == 'S')
            sponsorships.clean_invoices_paid(since_date, to_date,
                                             keep_lines=keep_lines)

        return super(SponsorshipContract, self)._clean_invoices(
            since_date, to_date, keep_lines)

    @api.multi
    def _on_sponsorship_finished(self):
        """ Called when a sponsorship is terminated or cancelled:
        Remove sponsor from the child and terminate related gift contracts.
        """
        for sponsorship in self:
            sponsorship.child_id.write({'sponsor_id': False})
            gift_contract_lines = self.env['recurring.contract.line'].search([
                ('sponsorship_id', '=', sponsorship.id)])
            for line in gift_contract_lines:
                contract = line.contract_id
                if len(contract.contract_line_ids) > 1:
                    line.unlink()
                else:
                    contract.signal_workflow('contract_terminated')

            # Cancel Sponsorship Message
            message_obj = self.env['gmc.message.pool']
            action_id = self.env.ref(
                'sponsorship_compassion.cancel_sponsorship').id

            message_vals = {
                'action_id': action_id,
                'object_id': sponsorship.id,
                'partner_id': sponsorship.correspondant_id.id,
                'child_id': sponsorship.child_id.id
            }
            message_obj.create(message_vals)

    @api.multi
    def contract_active(self):
        """ Hook for doing something when contract is activated.
        Update child to mark it has been sponsored,
        and activate gift contracts.
        Send messages to GMC.
        """
        for contract in self.filtered(
                lambda c: 'S' in c.type and not c.is_active):
            # UpsertConstituent Message
            partner = contract.correspondant_id
            partner.upsert_constituent()

            message_obj = self.env['gmc.message.pool']
            action_id = self.env.ref(
                'sponsorship_compassion.create_sponsorship').id

            message_vals = {
                'action_id': action_id,
                'object_id': contract.id
            }
            message_obj.create(message_vals)

        super(SponsorshipContract, self).contract_active()
        con_line_obj = self.env['recurring.contract.line']
        for contract in self.filtered(lambda c: 'S' in c.type):
            contract.child_id.write({'has_been_sponsored': True})
            gift_contract_lines = con_line_obj.search([
                ('sponsorship_id', '=', contract.id)])
            gift_contract_lines.mapped('contract_id').signal_workflow(
                'contract_active')

        return True

    @api.multi
    def _on_change_child_id(self, vals):
        """Link/unlink child to sponsor
        """
        child_id = vals.get('child_id')
        for contract in self:
            if 'S' in contract.type and contract.child_id and \
                    contract.child_id.id != child_id:
                # Free the previously selected child
                contract.child_id.write({'sponsor_id': False})
            if 'S' in contract.type:
                # Mark the selected child as sponsored
                self.env['compassion.child'].browse(child_id).write(
                    {'sponsor_id': vals.get('correspondant_id') or
                     contract.correspondant_id.id})

    @api.multi
    def invoice_paid(self, invoice):
        """ Prevent to reconcile invoices for fund-suspended projects
            or sponsorships older than 3 months. """
        for invl in invoice.invoice_line:
            if invl.contract_id and invl.contract_id.child_id:
                contract = invl.contract_id

                # Check contract is active or terminated recently.
                if contract.state == 'cancelled':
                    raise exceptions.Warning(
                        _("Reconcile error"),
                        _("The contract %s is not active.") % contract.name)
                if contract.state == 'terminated' and contract.end_date:
                    ended_since = date.today() - fields.Date.from_string(
                        contract.end_date)
                    if not ended_since.days <= 180:
                        raise exceptions.Warning(
                            _("Reconcile error"),
                            _("The contract %s is not active.")
                            % contract.name)

                # Check if project allows this kind of payment.
                payment_allowed = True
                project = contract.child_id.project_id
                if invl.product_id.categ_name == GIFT_CATEGORY:
                    payment_allowed = \
                        (not project.hold_gifts or
                         invl.due_date < project.status_date)
                elif invl.product_id.categ_name == SPONSORSHIP_CATEGORY:
                    payment_allowed = not project.hold_cdsp_funds or \
                        invl.due_date < project.status_date
                if not payment_allowed:
                    raise exceptions.Warning(
                        _("Reconcile error"),
                        _("The project %s is fund-suspended. You cannot "
                          "reconcile invoice (%s).") % (project.icp_id,
                                                        invoice.id))
        super(SponsorshipContract, self).invoice_paid(invoice)

    @api.one
    @api.constrains('group_id')
    def _is_a_valid_group(self):
        if 'S' in self.type:
            if not self.group_id.contains_sponsorship or\
                    self.group_id.recurring_value != 1:
                raise exceptions.ValidationError(_(
                    'You should select payment option with '
                    '"1 month" as recurring value'))
        return True

    @api.one
    @api.depends('contract_line_ids')
    def _has_valid_contract_lines(self, contract_lines, type):
        forbidden_product_types = {
            'O': [SPONSORSHIP_CATEGORY, GIFT_CATEGORY],
        }
        whitelist_product_types = {
            'G': [GIFT_CATEGORY],
            'S': [SPONSORSHIP_CATEGORY, FUND_CATEGORY],
            'SC': [SPONSORSHIP_CATEGORY, FUND_CATEGORY],
        }

        for contract_line in self.contract_line_ids.with_context(lang='en_US'):
            product = contract_line.product_id
            if product:
                categ_name = product.categ_name
                allowed = whitelist_product_types.get(self.type)
                forbidden = forbidden_product_types.get(self.type)
                if (allowed and categ_name not in allowed) or \
                        (forbidden and categ_name in forbidden):
                    message = _('You can only select {0} products.').format(
                        str(allowed)) if allowed else _(
                        'You should not select product '
                        'from category "{0}"'.format(categ_name))
                    raise exceptions.Warning(
                        _('Please select a valid product'), message)
        return True

    @api.multi
    def update_next_invoice_date(self):
        """ Override to force recurring_value to 1
            if contract is a sponsorship, and to bypass ORM for performance.
        """
        groups = self.mapped('group_id')
        for contract in self:
            if 'S' in contract.type:
                next_date = datetime.strptime(contract.next_invoice_date, DF)
                next_date += relativedelta(months=+1)
                next_date = next_date.strftime(DF)
            else:
                next_date = contract._compute_next_invoice_date()

            self.env.cr.execute(
                "UPDATE recurring_contract SET next_invoice_date = %s "
                "WHERE id = %s", (next_date, contract.id))
        self.env.invalidate_all()
        groups._set_next_invoice_date()
        return True

    @api.multi
    def _get_filtered_invoice_lines(self, invoice_lines):
        res = invoice_lines.filtered(
            lambda invl: invl.contract_id.id in self.ids and
            invl.product_id.categ_name != GIFT_CATEGORY)
        return res

    ##########################################################################
    #                      CLEAN PAID INVOICES METHODS                       #
    ##########################################################################
    @api.multi
    def _filter_clean_invoices(self, since_date=None, to_date=None,
                               gifts=False):
        """ Construct filter domain to be passed on method
        clean_invoices_paid, which will determine which invoice lines will
        be removed from invoices. """
        if not since_date:
            since_date = datetime.today().strftime(DF)
        invl_search = [('contract_id', 'in', self.ids), ('state', '=', 'paid'),
                       ('due_date', '>=', since_date),
                       ('product_id.categ_name', '!=', GIFT_CATEGORY)]
        if gifts:
            invl_search.pop()
        if to_date:
            invl_search.append(('due_date', '<=', to_date))

        return invl_search

    @api.multi
    def _how_to_clean_invl(self, inv_lines, to_remove_inv,
                           to_update_inv, to_remove_mvl, to_remove_move,
                           to_update_mvl, split_payment_mvl, unrec_pml,
                           invl_rm_data):
        """ Determine which action has to be done for each invoice_line for
        method clean_invoices_paid. See that method for the parameters.
        """
        to_update_inv.update(inv_lines.mapped('invoice_id.id'))

        invl_rm_data.update([
            (invl.id,
             [invl.invoice_id.id, invl.contract_id.child_code,
              invl.product_id.name, invl.price_subtotal])
            for invl in inv_lines.filtered(
                lambda invl: invl.contract_id.type == 'S')])
        for inv_line in inv_lines:
            invoice = inv_line.invoice_id
            mvl_found = False
            for mvl in inv_line.invoice_id.move_id.line_id:
                # 1. Update the move related with the invoice
                if not mvl_found and \
                        mvl.product_id.id == inv_line.product_id.id \
                        and mvl.credit == inv_line.price_subtotal \
                        and mvl.id not in to_remove_mvl:
                    # Mark mvl corresponding to invoice_line to be removed
                    to_remove_mvl.append(mvl.id)
                    mvl_found = True
                elif mvl.debit > 0 and mvl.account_id.code == '1050':
                    # Remove amount of invoice_line from debit line
                    # (the debit line corresponds to the total amount of
                    #  the invoice)
                    total_debit = to_update_mvl.get(mvl.id, mvl.debit)
                    to_update_mvl[mvl.id] = total_debit - \
                        inv_line.price_subtotal
                    if to_update_mvl[mvl.id] == 0:
                        # We deleted all invoice_lines and can delete the
                        # move associated with this invoice.
                        to_remove_mvl.append(mvl.id)
                        to_remove_move.append(mvl.move_id.id)

                    # 2. Update payment lines related with the invoice
                    for pml in mvl.reconcile_id.line_id:
                        if pml.credit > inv_line.price_subtotal:
                            amount_deleted = split_payment_mvl.get(pml.id,
                                                                   0.000)
                            split_payment_mvl[pml.id] = amount_deleted + \
                                inv_line.price_subtotal
                            if pml.credit == split_payment_mvl[pml.id]:
                                # The payment is fully unreconciled and thus
                                # don't need to be splitted
                                del split_payment_mvl[pml.id]
                                unrec_pml.append(pml.id)
                            elif pml.credit < split_payment_mvl[pml.id]:
                                self._clean_error()
                            # Update only one payment_line per invoice_line
                            break

            if not mvl_found:
                self._clean_error()

            # Mark empty invoice to be removed
            other_lines = invoice.mapped('invoice_line')
            remaining_lines_ids = other_lines.filtered(
                lambda invl: invl not in inv_lines).ids
            if not remaining_lines_ids:
                to_remove_inv.add(invoice.id)

        to_update_inv -= to_remove_inv

    @api.multi
    def _clean_paid_invoice_lines(self, to_remove_inv, to_update_inv,
                                  inv_line_ids, keep_lines=None):
        """ Remove or cancel the invoice lines.
        - to_remove_inv : invoices which are totally cleaned
        - to_update_inv : invoices which still contains valid invoice_lines
        """
        invoices = self.env['account.invoice'].browse(to_remove_inv)
        inv_line_obj = self.env['account.invoice.line']
        if keep_lines:
            # Cancel invoices instead of deleting them
            invoices.write({'move_id': False})
            invoices.signal_workflow('invoice_cancel')
            for invoice in invoices:
                invoice.message_post(_("Invoice Cancelled"), 'comment')

            # Isolate invoice lines in cancelled invoices instead of
            # deleting them
            invl_to_cancel = inv_line_obj.browse(inv_line_ids).filtered(
                lambda invl: invl.invoice_id.id in to_update_inv)

            self._move_cancel_lines(invl_to_cancel, keep_lines)

        else:
            # Delete invoice lines and empty invoices
            self.env.cr.execute(
                "DELETE FROM account_invoice_line WHERE id in ({0})"
                .format(','.join(str(id) for id in inv_line_ids)))
            if to_remove_inv:
                self.env.cr.execute(
                    "DELETE FROM account_invoice WHERE id in ({0})"
                    .format(','.join(str(id) for id in to_remove_inv)))
            self.env.invalidate_all()

    @api.multi
    def _clean_move_lines(self, to_remove_mvl, to_remove_move,
                          to_update_mvl):
        """ Remove move lines, invalid reconcile refs, empty moves and
        update total move lines of invoices after paid invoices were
        cleaned.
        """
        mvl_ids_string = ','.join(str(id) for id in to_remove_mvl)
        self.env.cr.execute(
            "DELETE FROM account_move_line WHERE id in ({0});"
            "DELETE FROM account_move_reconcile rec WHERE ("
            "   SELECT count(*) FROM account_move_line "
            "   WHERE reconcile_id = rec.id) < 2;"
            .format(mvl_ids_string))
        if to_remove_move:
            self.env.cr.execute(
                "DELETE FROM account_move WHERE id IN ({0})"
                .format(','.join(str(id) for id in to_remove_move)))
        for mvl, amount in to_update_mvl.iteritems():
            self.env.cr.execute(
                "UPDATE account_move_line SET debit={0:.3f} "
                "WHERE id = {1:d}".format(amount, mvl))
        self.env.invalidate_all()

    @api.multi
    def _unrec_split_payment(self, payment_data, unrec_pml):
        """ Method that splits a payment into two move_lines so that
        the amount which was cleaned from the paid invoice can be isolated
        and easily reconciled later.
        - payment_data (dict): {move_line_id: amount_cleaned}
        - unrec_pml (list): payment_lines which are totally unreconciled
        """
        mvl_obj = self.env['account.move.line']
        for pml_id, amount_deleted in payment_data.iteritems():
            self.env.cr.execute(
                "UPDATE account_move_line SET credit=credit-{0:.3f} "
                "WHERE id = {1:d}".format(
                    amount_deleted,
                    pml_id))
            # Copy payment move_line to put the amount unreconciled in a
            # separate move_line
            self.env.cr.execute("""
INSERT INTO account_move_line (
    statement_id, journal_id, date_maturity, partner_id, analytic_account_id,
    centralisation, company_id, state, blocked, ref, account_id, period_id,
    date, move_id, name, product_id, product_uom_id, quantity, analytics_id,
    transaction_ref
)

SELECT statement_id, journal_id, date_maturity, partner_id,
       analytic_account_id, centralisation, company_id, state, blocked, ref,
       account_id, period_id, date, move_id, name, product_id, product_uom_id,
       quantity, analytics_id, transaction_ref

FROM account_move_line WHERE id = %s""" % pml_id)

            # Update values of the newly inserted line
            self.env.cr.execute(
                "UPDATE account_move_line SET "
                "create_uid = {0:d}, write_uid = {0:d},"
                "create_date=now(), write_date=now(),"
                "credit={1:.3f} "
                "WHERE id = (SELECT max(id) FROM account_move_line)"
                .format(self.env.user.id, amount_deleted)
            )
            self.env.invalidate_all()
            # mvl_obj.browse(pml_id).copy({
            # 'reconcile_id': False,
            # 'credit': amount_deleted})
        if unrec_pml:
            mvl_obj.browse(unrec_pml)._remove_move_reconcile()

    @api.model
    def _set_demo_data(self):
        """ Set the state of the demo datas.
        Read the states from demo/recurring.contract.csv
        """
        file = THIS_DIR + '/../demo/recurring.contract.csv'
        with open(file, 'rb') as csvfile:
            reader = csv.reader(csvfile, delimiter=',')
            header = True
            for row in reader:
                if header:
                    contract_id = row.index('id')
                    state = row.index('state')
                    header = False
                    continue

                if row[state] == 'active':
                    self.env.ref('sponsorship_compassion.{}'.format(
                        row[contract_id])).contract_active()
                elif row[state] == 'draft':
                    continue
                elif row[state] == 'mandate':
                    self.env.ref('sponsorship_compassion.{}'.format(
                        row[contract_id])).contract_waiting_mandate()
                elif row[state] == 'waiting':
                    self.env.ref('sponsorship_compassion.{}'.format(
                        row[contract_id])).contract_waiting()

                elif row[state] == 'terminated':
                    self.env.ref('sponsorship_compassion.{}'.format(
                        row[contract_id])).contract_terminated()

                elif row[state] == 'cancelled':
                    self.env.ref('sponsorship_compassion.{}'.format(
                        row[contract_id])).contract_cancelled()
                else:
                    raise Warning('State not implemented')
