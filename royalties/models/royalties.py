# -*- coding: utf-8 -*-
# © 2017 Mackilem Van der Laan, Trustcode
# © 2017 Fillipe ramos, Trustcode
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).


from odoo import api, fields, models, _
from odoo.exceptions import ValidationError, Warning


class Royalties(models.Model):
    _name = 'royalties'

    name = fields.Char()
    validity_date = fields.Date(string=u"Validity Date")
    start_date = fields.Date(string=u"Start Date")
    royalty_type = fields.Char(string="Type")
    company_id = fields.Many2one("res.company", string="Company")
    payment_ids = fields.One2many("account.voucher", "royalties_id",
        readonly=True)
    line_ids = fields.One2many(
        'royalties.lines', 'royalties_id')
    partner_id = fields.Many2one('res.partner',
        string=u"Partner",
        required="1")
    region = fields.Char(string=u"Region", size=20)
    state = fields.Selection(
        [('draft','Draft'),('in_progress','in Progress'),
        ('waiting','Waiting Payment'),('done','Done')],
        default= 'draft',
        store=True,
        compute= '_compute_state')
    atived = fields.Boolean("Active")
    done = fields.Boolean("Contract Done")

    @api.one
    @api.constrains('validity_date')
    def _check_date(self):
        year, month, day = map(int, self.validity_date.split('-'))
        today = fields.Date.today()
        if self.validity_date < str(today):
            raise ValidationError(_("The validity date must be bigger then today"))
        elif year > int(today.split('-')[0]) + 12:
            raise ValidationError(_("The validity date can't be more then 12 years"))

    @api.multi
    def _compute_state(self):
        inv_royalties_obj = self.env['account.royalties.payment']
        for item in self:
            line_ids = inv_royalties_obj.search([('voucher_id', '=', False),
                ('royalties_id', '!=', False)])
            royalties_ids = line_ids.mapped('royalties_id')
            if item.atived and item.validity_date <= str(fields.Date.today()):
                if royalties_ids and item.id in royalties_ids.ids:
                    item.state = 'waiting'
                else:
                    item.atived = False
                    item.done = True
                    item.state = 'done'
            elif item.atived:
                item.state = 'in_progress'
            elif item.done:
                item.state = 'done'
            elif not item.atived and not item.done:
                item.state = 'draft'

    @api.multi
    def button_confirm(self):
        for item in self:
            item.start_date = fields.Date.today()
            item.atived = True

    @api.multi
    def button_back_draft(self):
        for item in self:
            item.atived = False

    @api.multi
    def button_done(self):
        for item in self:
            item.atived = False
            item.done = True

    @api.model
    def create(self,vals):
        sequence = self.env['ir.sequence'].next_by_code('royalties')
        vals.update({'name': sequence})
        return super(Royalties,self).create(vals)

    @api.multi
    def royalties_payment(self):
        inv_royalties_obj = self.env['account.royalties.payment']
        voucher_obj = self.env['account.voucher']
        journal_id = self.env['account.journal'].search([
            ('special_royalties', '=', True)])
        if not journal_id:
            raise Warning(_("The system didn't find the especific Account Journal"))

        for item in self:
            voucher_id = voucher_obj.search([
                ('royalties_id', '=', item.id),
                ('state', '=', 'draft')], limit= 1)
            if not voucher_id:
                vals = {
                    'partner_id': item.partner_id.id,
                    'account_id': item.partner_id.property_account_payable_id.id,
                    'date': fields.Date.today(),
                    'pay_now': 'pay_later',
                    'voucher_type': 'purchase',
                    'journal_id': journal_id.id,
                    'royalties_id': item.id,
                    'reference': 'Royalties Payment(%s)' % item.name,
                    }
                voucher_id = voucher_obj.create(vals)

            product_ids = item.line_ids.mapped('product_id')
            for prod_id in product_ids:
                royalties_line_ids = inv_royalties_obj.search(
                    [('voucher_id', '=', False),
                     ('royalties_id', '=', item.id),
                     ('product_id', '=', prod_id.id)])
                tax= (item._get_royalties_tax(royalties_line_ids,prod_id) / 100)

                for line in royalties_line_ids.mapped('inv_line_id'):
                    if item.partner_id.government:
                        amount = line.price_subtotal
                    else:
                        amount = line.product_id.list_price * line.quantity

                    line_vals = {
                        'product_id': line.product_id.id,
                        'name': 'Royalties (%s) :: %s' %
                            (item.name, line.invoice_id.number),
                        'price_unit': amount * tax,
                        'account_id':
                            voucher_id.journal_id.default_debit_account_id.id,
                        'company_id': line.company_id.id,
                        'inv_line_id': line.id,
                        }

                voucher_id.write({'line_ids':[(0,0,line_vals)]})
                line.write({'voucher_id': voucher_id.id})

    def _get_royalties_tax(self,royalties_line_ids,product_id):
        self.ensure_one()
        result = False

        royalties_line_ids = royalties_line_ids.mapped('inv_line_id')
        qty = sum([x.quantity for x in royalties_line_ids])
        for line in self.line_ids.sorted(key=lambda r: r.min_qty, reverse=True):
            if line.product_id.id == product_id.id and qty >= line.min_qty:
                    return line.commission
        return result


class RoyaltiesLines(models.Model):
    _name = 'royalties.lines'

    product_id = fields.Many2one(
        'product.product', string="Product", required=False)
    commission = fields.Float(string="% Commission")
    min_qty = fields.Float(string="Qty. minimum", default=1)
    royalties_id = fields.Many2one('royalties', string="Contracts")

    @api.one
    @api.constrains('commission')
    def _check_value(self):
        if self.commission < 0:
            raise ValidationError(
                _("The commission rate must be bigger them 0"))
        if self.commission > 100:
            raise ValidationError(
                _("The commission rate must be smaller them 100"))

    @api.one
    @api.constrains('commission')
    def _check_positive(self):
        if self.min_qty < 1:
            raise ValidationError(
                _("Quantity must be bigger them 1"))
