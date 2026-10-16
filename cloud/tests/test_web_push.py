import json,struct,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from scotus_cloud import webpush
from scotus_cloud.notifications import drain_notifications


def decrypt(body,receiver,auth):
    """The browser side of RFC 8291, to check what a device would read."""
    salt,(rs,idlen)=body[:16],struct.unpack('!IB',body[16:21])
    sender=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),body[21:21+idlen])
    secret=receiver.exchange(ec.ECDH(),sender)
    ikm=webpush._hkdf(auth,secret,b'WebPush: info\x00'+webpush._raw(receiver.public_key())+body[21:21+idlen],32)
    key=webpush._hkdf(salt,ikm,b'Content-Encoding: aes128gcm\x00',16)
    nonce=webpush._hkdf(salt,ikm,b'Content-Encoding: nonce\x00',12)
    plain=AESGCM(key).decrypt(nonce,body[21+idlen:],None)
    assert rs==4096 and plain.endswith(b'\x02')
    return plain[:-1]


class WebPushTests(unittest.TestCase):
    def setUp(self):
        self.receiver=ec.generate_private_key(ec.SECP256R1());self.auth=b'0123456789abcdef'
        self.subscription={'id':'device','endpoint':'https://web.push.apple.com/QOk','p256dh':webpush.b64(webpush._raw(self.receiver.public_key())),'auth':webpush.b64(self.auth)}
        private,public=webpush.generate_keys();self.settings={'private_key':private,'subject':'https://scotusstats.com/youtube/'};self.public=public

    def test_matches_rfc_8291_appendix_a(self):
        u=webpush.unb64
        sender=ec.derive_private_key(int.from_bytes(u('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'),'big'),ec.SECP256R1())
        body=webpush.encrypt(b'When I grow up, I want to be a watermelon','BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4',
                             'BTBZMqHH6r4Tts7J_aSIgg',salt=u('DGv6ra1nlYgDCS1FRnbzlw'),sender=sender)
        self.assertEqual(webpush.b64(body),'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_'
                         'yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')

    def test_payload_decrypts_on_the_device(self):
        body=webpush.encrypt(b'{"title":"Salazar"}',self.subscription['p256dh'],self.subscription['auth'])
        self.assertEqual(decrypt(body,self.receiver,self.auth),b'{"title":"Salazar"}')

    def test_vapid_token_is_signed_for_the_push_service_origin(self):
        header=webpush.vapid_header(self.subscription['endpoint'],self.settings['private_key'],self.settings['subject'],now=1000)
        token,key=header[len('vapid t='):].split(', k=')
        self.assertEqual(key,self.public)
        head,claims,signature=token.split('.')
        self.assertEqual(json.loads(webpush.unb64(claims)),{'aud':'https://web.push.apple.com','exp':1000+12*3600,'sub':'https://scotusstats.com/youtube/'})
        raw=webpush.unb64(signature);public=ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(),webpush.unb64(key))
        der=encode_dss_signature(int.from_bytes(raw[:32],'big'),int.from_bytes(raw[32:],'big'))
        public.verify(der,(head+'.'+claims).encode(),ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(InvalidSignature):public.verify(der,b'other',ec.ECDSA(hashes.SHA256()))

    def test_drain_sends_case_payload_and_reports_expired_devices(self):
        payload={'title':'Salazar v. Paramount Global','body':'3 annotation cards to review','hash':'#/case/x','badge':1}
        notice={'id':'n','token':'t','kind':'case_review','target':'review','payload':payload,
                'subscriptions':[self.subscription,{**self.subscription,'id':'old','endpoint':'https://web.push.apple.com/old'}]}
        dashboard=Mock();calls=iter([notice,None]);dashboard.call.side_effect=lambda op,**kw:next(calls) if op=='notification_claim' else None
        sent=[]
        def fake_send(subscription,data,settings,**kwargs):
            sent.append((subscription['id'],data));return 'sent' if subscription['id']=='device' else 'gone'
        with patch('scotus_cloud.notifications.webpush.send',side_effect=fake_send),patch('scotus_cloud.notifications.send_notice') as ntfy:
            drain_notifications(dashboard,{'web_push':self.settings,'dashboard_url':'https://example.org/','ntfy_fallback_enabled':True})
        ntfy.assert_not_called()
        self.assertEqual([s[0] for s in sent],['device','old']);self.assertEqual(sent[0][1],payload)
        dashboard.call.assert_any_call('notification_finish',id='n',token='t',sent=False,delivered=['device'],gone=['old'],web_push=True)

    def test_without_devices_the_generic_ntfy_notice_is_used(self):
        notice={'id':'n','token':'t','kind':'ready','target':'review','payload':{},'subscriptions':[]}
        dashboard=Mock();calls=iter([notice,None]);dashboard.call.side_effect=lambda op,**kw:next(calls) if op=='notification_claim' else None
        with patch('scotus_cloud.notifications.send_notice') as ntfy:
            drain_notifications(dashboard,{'web_push':self.settings,'dashboard_url':'https://example.org/','ntfy_fallback_enabled':True})
        ntfy.assert_called_once_with({'web_push':self.settings,'dashboard_url':'https://example.org/','ntfy_fallback_enabled':True},'ready','review')

    def test_partial_failure_is_returned_for_per_device_retry(self):
        notice={'id':'n','token':'t','kind':'ready','target':'r','payload':{},'subscriptions':[self.subscription,{**self.subscription,'id':'iphone'}]}
        dashboard=Mock();calls=iter([notice,None]);dashboard.call.side_effect=lambda op,**kw:next(calls) if op=='notification_claim' else None
        with patch('scotus_cloud.notifications.webpush.send',side_effect=lambda subscription,*args,**kwargs:'sent' if subscription['id']=='device' else 'failed'):
            drain_notifications(dashboard,{'web_push':self.settings})
        dashboard.call.assert_any_call('notification_finish',id='n',token='t',sent=False,delivered=['device'],gone=[],web_push=True)
    def test_ntfy_is_disabled_by_default(self):
        notice={'id':'n','token':'t','kind':'ready','target':'r','payload':{},'subscriptions':[]}
        dashboard=Mock();calls=iter([notice,None]);dashboard.call.side_effect=lambda op,**kw:next(calls) if op=='notification_claim' else None
        with patch('scotus_cloud.notifications.send_notice') as ntfy:drain_notifications(dashboard,{})
        ntfy.assert_not_called()
    def test_button_test_bypasses_other_notices_and_returns_delivery(self):
        dashboard=Mock();dashboard.call.side_effect=[{'id':'test','token':'lease','subscriptions':[{'id':'phone'}]},True]
        with patch('scotus_cloud.notifications.push_notice',return_value=(['phone'],[])):
            result=drain_notifications(dashboard,{'web_push':self.settings},notice_id='test')
        dashboard.call.assert_any_call('notification_claim',notice_id='test')
        self.assertEqual(result,[{'id':'test','delivered':1,'expired':0}])
    def test_dispatch_launches_work_before_notifying(self):
        from scotus_cloud.control import dispatch
        order=[]
        with patch('scotus_cloud.control._dispatch_work',side_effect=lambda *args:order.append('work') or {'launched':True}),patch('scotus_cloud.notifications.drain_notifications',side_effect=lambda *args:order.append('notices')):
            self.assertTrue(dispatch(Mock(),Mock(),{})['launched'])
        self.assertEqual(order,['work','notices'])

    def test_send_maps_push_service_responses(self):
        response=Mock(status=201);manager=Mock();manager.__enter__=Mock(return_value=response);manager.__exit__=Mock(return_value=False)
        with patch('scotus_cloud.webpush.urlopen',return_value=manager) as post:
            self.assertEqual(webpush.send(self.subscription,{'title':'x'},self.settings),'sent')
        request=post.call_args.args[0]
        self.assertEqual(request.headers['Content-encoding'],'aes128gcm');self.assertTrue(request.headers['Authorization'].startswith('vapid t='))
        self.assertEqual(json.loads(decrypt(request.data,self.receiver,self.auth)),{'title':'x'})
        from urllib.error import HTTPError
        with patch('scotus_cloud.webpush.urlopen',side_effect=HTTPError('u',410,'Gone',{},None)):
            self.assertEqual(webpush.send(self.subscription,{},self.settings),'gone')


if __name__=='__main__':unittest.main()
