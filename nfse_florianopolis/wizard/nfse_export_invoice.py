# -*- coding: utf-8 -*-
# © 2016 Danimar Ribeiro, Trustcode
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import os
import io
import re
import base64
from datetime import date
import os.path
from jinja2 import Environment, FileSystemLoader
from zipfile import ZipFile
from StringIO import StringIO
from odoo import api, fields, models
from odoo.exceptions import UserError


class NfseExportInvoice(models.TransientModel):
    _name = 'nfse.export.invoice'

    name = fields.Char('Nome', size=255)
    file = fields.Binary('Arquivo', readonly=True)
    state = fields.Selection(
       [('init', 'init'), ('done', 'done'), ],
       'state', readonly=True, default='init')

    def _invoice_vals(self, inv):
        tomador = {
            'cnpj_cpf': re.sub('[^0-9]', '', inv.partner_id.cnpj_cpf or ''),
            'inscricao_municipal': re.sub(
                '[^0-9]', '', inv.partner_id.inscr_mun or '0000000'),
            'name': inv.partner_id.legal_name,
            'street': inv.partner_id.street,
            'number': inv.partner_id.number,
            'district': inv.partner_id.district,
            'zip': re.sub('[^0-9]', '', inv.partner_id.zip or ''),
            'city_code': '%s%s' % (
                inv.partner_id.state_id.ibge_code,
                inv.partner_id.city_id.ibge_code),
            'uf_code': inv.partner_id.state_id.code,
            'email': inv.partner_id.email,
            'phone': re.sub('[^0-9]', '', inv.partner_id.phone or ''),
        }
        items = []
        for line in inv.invoice_line_ids:
            items.append({
                'name': line.product_id.name,
                'CNAE': re.sub('[^0-9]', '',
                               inv.company_id.cnae_main_id.code or ''),
                'CST': '1',
                'aliquota': line.issqn_aliquota / 100,
                'valor_unitario': line.price_unit,
                'quantidade': int(line.quantity),
                'valor_total': line.price_subtotal,
            })
        emissao = fields.Date.from_string(inv.date_invoice)
        cfps = '9201'
        if inv.company_id.city_id.id != inv.partner_id.city_id.id:
            cfps = '9202'
        if inv.company_id.state_id.id != inv.partner_id.state_id.id:
            cfps = '9203'
        return {
            'tomador': tomador,
            'items': items,
            'data_emissao': emissao.strftime('%Y-%m-%dZ'),
            'cfps': cfps,
            'base_calculo': inv.issqn_base,
            'valor_issqn': inv.issqn_value,
            'valor_total': inv.amount_total
        }

    def _export(self, invoice):
        vals = self._invoice_vals(invoice)
        base_path = os.path.dirname(os.path.dirname(__file__))
        env = Environment(
            loader=FileSystemLoader(
                os.path.join(base_path, 'template')))
        template = env.get_template('nfse.xml')
        xml = template.render(vals)
        xml = xml.replace('&', '&amp;')
        return {'name': u'{0}_{1}_nfse.xml'.format(
            invoice.internal_number,
            re.sub('[^A-Za-z]', '', invoice.partner_id.name)),
            'content': xml}

    def _save_zip(self, xmls):
        tmp = '/tmp/odoo/nfse-export/'
        try:
            os.makedirs(tmp)
        except:
            pass
        zip_base64 = StringIO()
        zipFile = ZipFile(zip_base64, 'w')
        for xml in xmls:
            filename = os.path.join(tmp, xml['name'])
            with io.open(filename, 'w', encoding='utf8') as xml_file:
                xml_file.write(xml['content'])
            zipFile.write(filename, xml['name'])
        zipFile.close()
        zip_base64.seek(0)
        return base64.b64encode(zip_base64.getvalue())

    @api.multi
    def nfse_export(self):
        self.state = 'done'
        active_ids = self.env.context.get('active_ids', [])

        invoice_ids = self.env['account.invoice'].browse(active_ids)
        xmls = []
        for invoice in invoice_ids:
            errors = []
            if invoice.partner_id.is_company and\
                    not invoice.partner_id.legal_name:
                errors += ['Razão Social incompleta.']
            if not invoice.partner_id.phone and invoice.partner_id.mobile:
                invoice.partner_id.phone = invoice.partner_id.mobile
            if not invoice.partner_id.phone and not invoice.\
                    partner_id.mobile:
                errors += ['Telefone incompleto.']
            if not invoice.partner_id.city_id:
                errors += ['Munícipio incompleto.']
            if not invoice.partner_id.zip:
                errors += ['CEP incompleto.']
            if not invoice.partner_id.cnpj_cpf:
                errors += ['CPF / CNPJ incompleto.']
            if not invoice.partner_id.street:
                errors += ['Logradouro incompleto.']
            if not invoice.partner_id.email:
                errors += ['Email incompleto.']
            if len(errors) > 0:
                err = ''.join(errors)
                error_msg = '%s\n' % invoice.move_name
                error_msg += err
                raise UserError(error_msg)
            invoice.date_invoice = date.today()
            xmls.append(self._export(invoice))

        self.file = self._save_zip(xmls)
        self.name = 'xml_nfse_exportacao.zip'

        mod_obj = self.env['ir.model.data'].search(
            [('model', '=', 'ir.ui.view'),
             ('name', '=',
              'view_nfse_florianopolis_nfse_export_invoice_form')])

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'view_type': 'form',
            'res_id': self.id,
            'views': [(mod_obj.res_id, 'form')],
            'target': 'new',
        }
